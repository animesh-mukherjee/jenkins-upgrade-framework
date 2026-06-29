# jenkins-upgrade-framework

A lightweight **check-and-report** framework that tells you when your Jenkins
core (LTS) or plugins are behind the latest published versions. It runs in
GitHub Actions on demand (and weekly), and **never modifies your repo** — no
file edits, no PRs. You decide what to upgrade.

## How it works

Your pinned versions live in two files:

| File | What it pins |
|------|--------------|
| `.jenkins-version` | Jenkins core LTS version (e.g. `2.452.1`) |
| `jenkins/plugins.txt` | Plugins, one `id:version` per line |

The checker reads them and diffs against the Jenkins update center:

- Latest core LTS → `https://updates.jenkins.io/stable/latestCore.txt`
- Plugin catalog → `https://updates.jenkins.io/current/update-center.actual.json`
  (used for each plugin's latest `version` and its `requiredCore`)

It then prints a markdown report and, in CI, writes it to the run's
**Step Summary**. For each outdated plugin it also flags when the update
**requires a newer core** than your target, so you don't pull a plugin your
controller can't load.

## Running it

On demand: GitHub → **Actions** → **Check Jenkins Updates** → **Run workflow**.
Optionally tick *fail_on_outdated* to make the run go red when something is behind.

It also runs automatically every **Monday 06:00 UTC**.

Locally:

```bash
python3 scripts/check_updates.py
```

Flags:

- `--fail-on-outdated` — exit 1 if core or any plugin is behind
- `--fail-on-error` — exit 1 if the update center couldn't be reached

## Adapting to your Jenkins

Replace the sample values in `.jenkins-version` and `jenkins/plugins.txt` with
your real pinned versions (the same `plugins.txt` your controller installs from
via `jenkins-plugin-cli --plugin-file`). `jenkins/jenkins.yaml` is a sample
JCasC config — the checker doesn't parse it; it's there so the repo reflects a
real JCasC + plugins.txt layout.

## Layout

```
.jenkins-version                       # pinned core LTS
jenkins/plugins.txt                    # pinned plugins (id:version)
jenkins/jenkins.yaml                   # JCasC config (sample)
scripts/check_updates.py               # the checker
.github/workflows/check-jenkins-updates.yml
```

## Possible extensions

This is intentionally report-only. If you later want it to act, natural next
steps are: open a tracking Issue with the report, or graduate to a PR-raising
workflow that bumps `plugins.txt`/`.jenkins-version` and spins up Jenkins in CI
to verify plugins load.
