#!/usr/bin/env python3
"""
check_updates.py
================
Check-and-report tool for the jenkins-upgrade-framework.

Reads the pinned Jenkins core LTS version (`.jenkins-version`) and the pinned
plugin list (`jenkins/plugins.txt`), compares them against the latest versions
published by the Jenkins update center, and writes a markdown report.

It changes NOTHING in the repo. Output goes to stdout and, when running inside
GitHub Actions, to the job's Step Summary ($GITHUB_STEP_SUMMARY).

Data sources (public, no auth):
  - Latest core LTS:  https://updates.jenkins.io/stable/latestCore.txt
  - Plugin catalog:   https://updates.jenkins.io/current/update-center.actual.json
      (each plugin entry exposes `version` and `requiredCore`)

Exit code:
  0 always by default. Pass --fail-on-outdated to exit 1 when anything is behind
  (useful if you later want a red check). Pass --fail-on-error to exit 1 on a
  fetch/parse failure instead of degrading gracefully.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

LATEST_CORE_URL = "https://updates.jenkins.io/stable/latestCore.txt"
UPDATE_CENTER_URL = "https://updates.jenkins.io/current/update-center.actual.json"

REPO_ROOT = Path(__file__).resolve().parent.parent
CORE_VERSION_FILE = REPO_ROOT / ".jenkins-version"
PLUGINS_FILE = REPO_ROOT / "jenkins" / "plugins.txt"

HTTP_TIMEOUT = 30
USER_AGENT = "jenkins-upgrade-framework/1.0 (+https://github.com)"


# --------------------------------------------------------------------------- #
# Version comparison
# --------------------------------------------------------------------------- #
def version_key(version: str):
    """
    Best-effort comparable key for Jenkins-style versions.

    Jenkins versions are mostly numeric-dotted ("2.452.1") but plugin versions
    can be hash-suffixed ("1836.vccda4a909a_73"). We compare the leading
    dotted-numeric portion of each dot-separated token and keep the raw token
    as a tiebreaker so comparison is stable and never raises.
    """
    key = []
    for token in str(version).split("."):
        num = ""
        for ch in token:
            if ch.isdigit():
                num += ch
            else:
                break
        key.append((int(num) if num else -1, token))
    return key


def is_newer(latest: str, current: str) -> bool:
    try:
        return version_key(latest) > version_key(current)
    except Exception:
        return latest != current


# --------------------------------------------------------------------------- #
# Parsing pinned versions
# --------------------------------------------------------------------------- #
def read_core_version() -> str | None:
    if not CORE_VERSION_FILE.exists():
        return None
    text = CORE_VERSION_FILE.read_text(encoding="utf-8").strip()
    return text or None


def read_pinned_plugins() -> dict[str, str]:
    """Return {plugin_id: pinned_version} from plugins.txt."""
    plugins: dict[str, str] = {}
    if not PLUGINS_FILE.exists():
        return plugins
    for raw in PLUGINS_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            # Unpinned (e.g. "git:latest" style or bare id) — record with no version.
            plugins[line] = ""
            continue
        pid, ver = line.split(":", 1)
        plugins[pid.strip()] = ver.strip()
    return plugins


# --------------------------------------------------------------------------- #
# Fetching update-center data
# --------------------------------------------------------------------------- #
def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return resp.read()


def fetch_latest_core() -> str | None:
    try:
        return _fetch(LATEST_CORE_URL).decode("utf-8").strip()
    except Exception as exc:
        print(f"::warning::could not fetch latest core: {exc}", file=sys.stderr)
        return None


def fetch_plugin_catalog() -> dict[str, dict]:
    """
    Return {plugin_id: {"version": str, "requiredCore": str}} from the
    update-center catalog. Returns {} on failure.
    """
    try:
        data = json.loads(_fetch(UPDATE_CENTER_URL).decode("utf-8"))
    except Exception as exc:
        print(f"::warning::could not fetch update center: {exc}", file=sys.stderr)
        return {}
    out: dict[str, dict] = {}
    for pid, meta in data.get("plugins", {}).items():
        out[pid] = {
            "version": meta.get("version", ""),
            "requiredCore": meta.get("requiredCore", ""),
        }
    return out


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
@dataclass
class PluginRow:
    pid: str
    current: str
    latest: str
    required_core: str
    outdated: bool
    needs_core: bool  # latest plugin needs a newer core than we'd have


@dataclass
class Report:
    core_current: str | None
    core_latest: str | None
    core_outdated: bool
    plugins: list[PluginRow] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def effective_core(self) -> str | None:
        """The core we assume after a core upgrade is applied."""
        return self.core_latest or self.core_current

    @property
    def outdated_count(self) -> int:
        return sum(1 for p in self.plugins if p.outdated)


def build_report(
    core_current: str | None,
    core_latest: str | None,
    pinned: dict[str, str],
    catalog: dict[str, dict],
) -> Report:
    core_outdated = bool(
        core_current and core_latest and is_newer(core_latest, core_current)
    )
    rep = Report(
        core_current=core_current,
        core_latest=core_latest,
        core_outdated=core_outdated,
    )
    effective_core = core_latest or core_current

    for pid in sorted(pinned):
        current = pinned[pid]
        meta = catalog.get(pid)
        if not meta:
            rep.plugins.append(
                PluginRow(pid, current or "?", "unknown", "", False, False)
            )
            rep.notes.append(f"`{pid}` not found in update center (renamed/removed?).")
            continue
        latest = meta["version"]
        req_core = meta.get("requiredCore", "")
        outdated = bool(current) and is_newer(latest, current)
        needs_core = bool(
            req_core and effective_core and is_newer(req_core, effective_core)
        )
        rep.plugins.append(
            PluginRow(pid, current or "(unpinned)", latest, req_core, outdated, needs_core)
        )
    return rep


def render_markdown(rep: Report) -> str:
    lines: list[str] = []
    lines.append("# Jenkins Update Report")
    lines.append("")

    # Core
    lines.append("## Core (LTS)")
    lines.append("")
    if rep.core_current is None:
        lines.append("- Pinned core version not found (`.jenkins-version` missing).")
    elif rep.core_latest is None:
        lines.append(f"- Current: `{rep.core_current}` — latest LTS unavailable (fetch failed).")
    elif rep.core_outdated:
        lines.append(
            f"- ⚠️ **Outdated** — current `{rep.core_current}` → latest LTS "
            f"**`{rep.core_latest}`**"
        )
    else:
        lines.append(f"- ✅ Up to date — `{rep.core_current}` (latest LTS `{rep.core_latest}`)")
    lines.append("")

    # Plugins
    lines.append("## Plugins")
    lines.append("")
    if not rep.plugins:
        lines.append("- No plugins pinned.")
    else:
        lines.append("| Status | Plugin | Current | Latest | Requires core | Note |")
        lines.append("|:------:|--------|---------|--------|---------------|------|")
        # outdated first, then alpha
        for p in sorted(rep.plugins, key=lambda r: (not r.outdated, r.pid)):
            if p.latest == "unknown":
                status = "❓"
            elif p.outdated:
                status = "⚠️"
            else:
                status = "✅"
            note = ""
            if p.needs_core:
                note = f"needs core ≥ {p.required_core}"
            lines.append(
                f"| {status} | `{p.pid}` | {p.current} | {p.latest} | "
                f"{p.required_core or '—'} | {note} |"
            )
    lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Core outdated: **{'yes' if rep.core_outdated else 'no'}**")
    lines.append(
        f"- Plugins outdated: **{rep.outdated_count} / {len(rep.plugins)}**"
    )
    blocked = [p.pid for p in rep.plugins if p.outdated and p.needs_core]
    if blocked:
        lines.append(
            f"- ⚠️ {len(blocked)} plugin update(s) require a newer core than the "
            f"target (`{rep.effective_core}`): {', '.join('`'+b+'`' for b in blocked)}"
        )
    lines.append("")

    if rep.notes:
        lines.append("## Notes")
        lines.append("")
        for n in rep.notes:
            lines.append(f"- {n}")
        lines.append("")

    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="Report outdated Jenkins core/plugins.")
    ap.add_argument("--fail-on-outdated", action="store_true",
                    help="Exit 1 if core or any plugin is outdated.")
    ap.add_argument("--fail-on-error", action="store_true",
                    help="Exit 1 if update-center data could not be fetched.")
    args = ap.parse_args()

    core_current = read_core_version()
    pinned = read_pinned_plugins()

    core_latest = fetch_latest_core()
    catalog = fetch_plugin_catalog()

    fetch_failed = core_latest is None or not catalog

    rep = build_report(core_current, core_latest, pinned, catalog)
    md = render_markdown(rep)

    print(md)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(md + "\n")

    if args.fail_on_error and fetch_failed:
        return 1
    if args.fail_on_outdated and (rep.core_outdated or rep.outdated_count > 0):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
