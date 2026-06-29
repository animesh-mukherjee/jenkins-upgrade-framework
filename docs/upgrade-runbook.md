# Jenkins Upgrade Runbook

This runbook covers upgrading Jenkins core and plugins in the `jenkins-upgrade-framework`. The Helm chart is the deployment artifact; the Python checker detects what's outdated.

---

## Prerequisites

| Tool | Purpose |
|------|---------|
| `helm` ≥ 3.14 | Deploy / upgrade the chart |
| `kubectl` | Watch rollouts, get secrets |
| `python3` | Run the update checker locally |
| Access to the cluster | kubeconfig pointing at your cluster |

---

## Step 1 — Detect outdated versions

```bash
python3 scripts/check_updates.py
```

This reads `.jenkins-version` (core) and `jenkins/plugins.txt` (plugins) and compares against the Jenkins update center. The report shows:

- `⚠️` — outdated, update available
- `✅` — up to date
- `❓` — plugin not found in update center (may have been renamed)

---

## Step 2 — Update core version

1. Open `helm/jenkins/values.yaml`.
2. Change `image.tag` to the new LTS tag, e.g.:
   ```yaml
   image:
     tag: "2.462.1-lts"
   ```
3. Update `Chart.yaml` `appVersion` to match:
   ```yaml
   appVersion: "2.462.1-lts"
   ```
4. Update `.jenkins-version` (keeps the checker in sync):
   ```
   2.462.1
   ```

---

## Step 3 — Update plugin versions

1. Open `jenkins/plugins.txt` (the checker's source of truth).
2. Bump each outdated plugin to its new pinned version, e.g.:
   ```
   git:5.3.0
   ```
3. Copy the same changes into `helm/jenkins/files/plugins.txt` (the chart's copy).

The init container will reinstall all plugins from the updated list on the next pod start.

---

## Step 4 — Validate locally (no cluster needed)

```bash
# Lint — catches template syntax errors
helm lint ./helm/jenkins

# Render to stdout — eyeball the generated manifests
helm template jenkins ./helm/jenkins --debug | less
```

---

## Step 5 — Deploy / upgrade

### Option A — Manual (KodeKloud, local cluster)

```bash
helm upgrade --install jenkins ./helm/jenkins \
  --namespace jenkins \
  --create-namespace \
  --atomic \
  --timeout 10m \
  --wait
```

### Option B — GitHub Actions

Push the version bumps to `main`. The `helm-upgrade.yml` workflow triggers automatically when `helm/jenkins/values.yaml` or either `files/` config changes.

Or trigger it manually:
**Actions → Helm Upgrade — Jenkins → Run workflow**

> **Required secret:** `KUBECONFIG_B64` — base64-encoded kubeconfig for your cluster.
>
> Generate it:
> ```bash
> cat ~/.kube/config | base64 -w 0
> ```
> Paste the output into **Settings → Secrets → KUBECONFIG_B64**.

---

## Step 6 — Monitor rollout

```bash
kubectl rollout status deployment/jenkins -n jenkins --timeout=10m
```

Watch pod logs during startup (plugin install + JCasC load):

```bash
kubectl logs -f deployment/jenkins -n jenkins --all-containers
```

---

## Step 7 — Verify Jenkins is healthy

```bash
# NodePort URL
NODE_IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[0].address}')
NODE_PORT=$(kubectl get svc jenkins -n jenkins -o jsonpath='{.spec.ports[?(@.name=="http")].nodePort}')
echo "Jenkins: http://$NODE_IP:$NODE_PORT"

# Retrieve admin password (if auto-generated)
kubectl get secret jenkins -n jenkins \
  -o jsonpath='{.data.jenkins-admin-password}' | base64 -d && echo
```

Log in, confirm the version shown in **Manage Jenkins → About Jenkins**, and run a test build.

---

## Rollback

If the upgrade fails or Jenkins is unhealthy:

```bash
# Roll back to the previous Helm release revision
helm rollback jenkins -n jenkins

# Or roll back two revisions
helm rollback jenkins 0 -n jenkins
```

List available revisions:

```bash
helm history jenkins -n jenkins
```

---

## Keeping the two plugins.txt files in sync

| File | Read by |
|------|---------|
| `jenkins/plugins.txt` | `scripts/check_updates.py` (checker) |
| `helm/jenkins/files/plugins.txt` | Helm chart ConfigMap → init container |

Both must be updated together. A future enhancement is a CI step that diffs them and fails the workflow if they diverge.

---

## Upgrade checklist

- [ ] `check_updates.py` report reviewed
- [ ] `image.tag` updated in `values.yaml`
- [ ] `appVersion` updated in `Chart.yaml`
- [ ] `.jenkins-version` updated
- [ ] `jenkins/plugins.txt` updated
- [ ] `helm/jenkins/files/plugins.txt` updated (same changes)
- [ ] `helm lint` passes
- [ ] `helm template` output reviewed
- [ ] `helm upgrade --install ... --atomic --wait` succeeded
- [ ] Rollout status healthy
- [ ] Jenkins UI accessible and shows correct version
- [ ] Test build passes
