# RunIt App - Ship, Break and Recover

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-container-2496ED?logo=docker&logoColor=white)
![Azure Container Apps](https://img.shields.io/badge/Azure-Container%20Apps-0078D4?logo=microsoftazure&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/CI%2FCD-GitHub%20Actions-2088FF?logo=githubactions&logoColor=white)

A small Python web app, containerised with Docker and deployed to **Azure Container Apps** by a **GitHub Actions** pipeline on every push to `main`. It's run with the basics of reliability engineering: a health check, an SLO, fail-fast configuration, a pipeline that verifies every release, a one-command rollback and a blameless postmortem.

This repo is the result of **two incident drills**:

| | Drill 1: the original incident | Drill 2: same bug, fail-fast |
|---|---|---|
| Users | ❌ 0/20 requests succeeded | ✅ 20/20 throughout |
| Detected by | `check.sh` and the logs | Azure (failed revision) and the pipeline (red in 26 s) |
| Fix | `git revert` (3 min 22 s to restore) | Set the missing config and redeploy |

> Built from the *RunIt Weekend: Ship, Break and Recover an App* lab, then extended after reader feedback.

---

## Table of contents

- [Architecture](#architecture)
- [Repository structure](#repository-structure)
- [The app](#the-app)
- [Configuration](#configuration)
- [Reliability](#reliability)
- [Run locally](#run-locally)
- [Deploy](#deploy)
- [Roll back](#roll-back)
- [Incident drills](#incident-drills)
- [Lessons learned](#lessons-learned)
- [Clean up](#clean-up)
- [Author](#author)

---

## Architecture

```
 git push (main)
      │
      ▼
 GitHub Actions
   ├─► build image ──► push to GHCR (tag = commit SHA)
   ├─► az containerapp update (service principal, scoped to runit-rg)
   ├─► verify the new revision is Running + Healthy ──► ❌ fail the pipeline if not
   └─► smoke test: check.sh against the live URL ──────► ❌ fail the pipeline if SLO broken
                                │
                                ▼
                     Azure Container Apps (single revision mode)
                     new revision gets traffic only once it's ready
                                │
                                ▼
                     users          Log Analytics (logs)
```

| Component | Purpose |
|---|---|
| **Python app** (standard library only) | Serves the home page and a `/health` endpoint |
| **Docker** | Packages the app; runs as non-root with a `HEALTHCHECK` |
| **GitHub Container Registry (GHCR)** | Stores images, each tagged with the commit SHA |
| **GitHub Actions** | Builds, pushes, deploys, verifies and smoke-tests every push to `main` |
| **Azure Container Apps** | Runs the container; only shifts traffic to a revision once it's ready |
| **Log Analytics** | Collects console and system logs used to diagnose incidents |
| **Service principal** | Pipeline identity, scoped to the `runit-rg` resource group only (least privilege) |

---

## Repository structure

```
runit-app/
├── .github/
│   └── workflows/
│       └── deploy.yml      # CI/CD: build → push → deploy → verify revision → smoke test
├── app.py                  # The web app (/ and /health)
├── Dockerfile              # Container image with HEALTHCHECK, non-root user
├── check.sh                # Quick SLO check: 20 requests to the home page
├── postmortem.md           # Blameless postmortem, with the fail-fast follow-up
└── README.md
```

---

## The app

| Endpoint | Response | Purpose |
|---|---|---|
| `GET /` | `200` HTML home page with today's discount | What users see |
| `GET /health` | `200` `{"status": "ok"}` | Liveness: the process is running |

Unexpected errors on the home page are caught, logged with the request path and returned as a clean `500`, so one bad request never takes the process down.

---

## Configuration

| Variable | Required? | Default | Behaviour if missing |
|---|---|---|---|
| `DISCOUNT_PERCENT` | **Yes** | none | App **exits at startup** (`KeyError`). The new revision never becomes ready, so traffic stays on the previous one. |
| `MESSAGE` | No | `Hello from ShipIt Weekend!` | Uses the default |
| `PORT` | No | `8080` | Uses the default |

**Rule:** required settings are read **once at startup** with `os.environ["..."]`, outside any `try/except`, so a misconfigured release fails at deploy, not in front of users. Only truly optional settings use `os.environ.get(..., default)`.

Set or change a value in Azure:

```bash
az containerapp update --name runit-app --resource-group runit-rg --set-env-vars DISCOUNT_PERCENT=20
```

---

## Reliability

### SLO

> **99.5% of requests to the home page succeed (HTTP 200), measured over 30 days.**

That gives an **error budget** of about **3.6 hours a month**.

### Quick SLO check

`check.sh` sends 20 requests to the **home page** (not `/health`) and reports the success rate:

```bash
bash check.sh                      # local: http://localhost:8080
bash check.sh https://<your-app-url>
```

```
20/20 requests succeeded (100%) at https://<your-app-url>
SLO met (95% or more)
```

19/20 or better means we're within the SLO. The pipeline runs the same check after every deploy.

### Health check

`GET /health` returns `{"status": "ok"}` while the process is running. The Dockerfile's `HEALTHCHECK` uses it for local Docker runs.

> ⚠️ **A health check is not an SLO.** `/health` proves the process is alive, not that users get a working page. Drill 1 is the proof.

---

## Run locally

**Prerequisites:** Docker.

```bash
# Build the image
docker build -t runit-app:good .

# Run it (DISCOUNT_PERCENT is required)
docker run -d -p 8080:8080 -e DISCOUNT_PERCENT=20 --name runit runit-app:good

# Check health and the SLO
curl -s localhost:8080/health; echo
bash check.sh

# Stop it
docker rm -f runit
```

Run it **without** `-e DISCOUNT_PERCENT=20` and the container exits immediately. That's fail-fast working as intended.

---

## Deploy

Every push to `main` deploys automatically through [`.github/workflows/deploy.yml`](.github/workflows/deploy.yml):

1. Check out the code.
2. Log in to GHCR with the built-in `GITHUB_TOKEN`.
3. Build and push `ghcr.io/<owner>/runit-app:<short-sha>`.
4. Log in to Azure with the `AZURE_CREDENTIALS` secret.
5. Run `az containerapp update` to create a new revision with the new image.
6. **Verify the new revision:** poll it every 10 s; pass when it's `Running` + `Healthy`, fail when it's `Failed` or after 5 minutes.
7. **Smoke test:** run `check.sh` against the live URL; fail unless the SLO is met.

Steps 6 and 7 exist because `az containerapp update` reports success as soon as Azure **accepts** the new revision, not when it's actually **serving**. Without them, a release that never went live still shows a green pipeline.

The workflow can also be run manually from the **Actions** tab (`workflow_dispatch`).

### First-time setup

<details>
<summary>Click to expand</summary>

**1. Publish the first image**

```bash
export GH_USER=<your-github-username>
echo <TOKEN_WITH_write:packages> | docker login ghcr.io -u $GH_USER --password-stdin
docker build -t ghcr.io/$GH_USER/runit-app:v1 .
docker push ghcr.io/$GH_USER/runit-app:v1
```

In the package settings on GitHub:
- **Change visibility → Public**, so Azure can pull the image without credentials.
- **Manage Actions access → Add Repository → `runit-app` → Write**, so the pipeline can push new images.

**2. Create the Azure resources**

```bash
az login --use-device-code
az extension add --name containerapp --upgrade
az provider register --namespace Microsoft.App --wait
az provider register --namespace Microsoft.OperationalInsights --wait
az group create --name runit-rg --location westeurope
az containerapp up --name runit-app --resource-group runit-rg --location westeurope \
  --image ghcr.io/$GH_USER/runit-app:v1 --ingress external --target-port 8080
az containerapp update --name runit-app --resource-group runit-rg --set-env-vars DISCOUNT_PERCENT=20
```

**3. Give the pipeline access to Azure**

```bash
SUB_ID=$(az account show --query id -o tsv)
az ad sp create-for-rbac --name runit-github --role contributor \
  --scopes /subscriptions/$SUB_ID/resourceGroups/runit-rg --json-auth
```

Save the JSON output as a repository secret named **`AZURE_CREDENTIALS`** (Settings → Secrets and variables → Actions).

If you recreate `runit-rg` later, the service principal loses its access (the role was scoped to the old group). Re-grant it:

```bash
az role assignment create \
  --assignee $(az ad sp list --display-name runit-github --query "[0].appId" -o tsv) \
  --role contributor --scope /subscriptions/$SUB_ID/resourceGroups/runit-rg
```

</details>

### Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Pipeline fails with `permission_denied: write_package` | The repo's Actions token can't write to a package that was first pushed manually | Package settings → **Manage Actions access** → add `runit-app` with **Write** |
| **Verify the new revision** fails with "failed to start" | The new container crashes on boot, e.g. a required setting is missing | `az containerapp logs show -n runit-app -g runit-rg --type system`; set the missing value with `--set-env-vars` |
| Revision list shows 100% traffic on a **Failed** revision | `trafficWeight` is the *configured* routing; in single revision mode, real traffic stays on the previous revision until the new one is ready | Trust `check.sh`, not the table |
| `az containerapp up` stays on "Running" after creating the environment | The CLI stopped polling, even though Azure finished | Check `az containerapp env show ... --query properties.provisioningState`; if `Succeeded`, cancel and re-run, and it reuses the environment |
| `az extension add` hangs on "Searching" | Network or DNS hiccup fetching the extension index (seen in WSL) | Check `az extension show --name containerapp`; skip if already installed |

### Reading logs

```bash
# App output (what print() writes)
az containerapp logs show -n runit-app -g runit-rg --tail 20

# Platform events: container started, exited, restarted
az containerapp logs show -n runit-app -g runit-rg --type system --tail 30

# Console output of a revision that has no replicas left (from Log Analytics)
LAW_ID=$(az containerapp env show -n runit-app-env -g runit-rg \
  --query properties.appLogsConfiguration.logAnalyticsConfiguration.customerId -o tsv)
az monitor log-analytics query -w $LAW_ID -o table --analytics-query \
  "ContainerAppConsoleLogs_CL | where RevisionName_s == '<revision-name>' | project TimeGenerated, Log_s | order by TimeGenerated asc"
```

---

## Roll back

Rollback is just another commit. It goes through the same pipeline as every other change:

```bash
git revert --no-edit <bad-commit>
git push
```

`git revert` keeps history intact, so there's nothing special to run and nothing is deleted.

---

## Incident drills

### Drill 1: the original incident

I shipped a "discount" feature that read `DISCOUNT_PERCENT` **on every request**. It was never set in production.

| | Result |
|---|---|
| Pipeline | ✅ green |
| `/health` | ✅ `{"status": "ok"}` |
| `check.sh` | ❌ **0/20 requests succeeded, SLO broken** |
| Logs | `ERROR serving /: KeyError('DISCOUNT_PERCENT')` |
| Fix | `git revert` + push |
| **Time to restore** | **3 minutes 22 seconds** |

The `try/except` kept the process alive, so `/health` stayed green and Azure sent every request to the broken version.

### Drill 2: same bug, fail-fast

After [reader feedback](postmortem.md#follow-up-re-running-the-drill-with-fail-fast-config), I moved the read to **startup** and shipped the same bug again, still without the setting.

| | Result |
|---|---|
| New revision | ❌ crashed in 0.3 s (`exit code 1`), retried 5 times with backoff, marked **Failed** |
| Traffic | Stayed on the previous revision |
| `check.sh` | ✅ **20/20 throughout** |
| Original pipeline | ✅ green (it only checked that Azure accepted the update) |
| Pipeline with revision check | ❌ **red in 26 s**: "Revision failed to start. Traffic stayed on the previous revision." |
| Fix | `--set-env-vars DISCOUNT_PERCENT=20` → healthy revision → discount live |
| **User impact** | **None** |

Full write-up: **[postmortem.md](postmortem.md)**

---

## Lessons learned

- **Green doesn't mean working.** In Drill 1, the pipeline and the health check were both green while 0% of users could load the page. Measure the path users actually take.
- **Fail fast on required config.** A missing required setting should stop the process at startup, not fail on every request. On Azure Container Apps (single revision mode), a revision that never becomes ready never receives traffic.
- **A green deploy step isn't a live release.** `az containerapp update` succeeds once Azure accepts the change. Verify the new revision is actually healthy before calling it done.
- **Configured traffic isn't actual traffic.** The revision list showed 100% weight on a failed revision while every request was served by the old one.
- **Make rollback boring.** The normal deploy path is the rollback path.

### Improvements

- [x] Read required settings at startup and fail fast; use safe defaults only for optional ones
- [x] Verify the new revision is healthy after every deploy
- [x] Smoke test `/` in the pipeline after every deploy
- [x] Re-run the drill with fail-fast config and compare the results
- [ ] Alert when the success rate drops below the SLO
- [ ] Bump GitHub Actions to versions that run natively on Node.js 24

---

## Clean up

Azure resources are torn down after each drill to avoid cost:

```bash
az group delete --name runit-rg --yes --no-wait
```

The repo, the postmortem and the container images in GHCR remain.

---

## Author

**Rahimah Sulayman** - DevOps / Cloud Engineer

- GitHub: [@rahimahisah17](https://github.com/rahimahisah17)
- DEV: [@rahimah_dev](https://dev.to/rahimah_dev)
- Part 1: https://dev.to/rahimah_dev/ship-it-break-it-fix-it-running-a-python-app-on-azure-container-apps-with-an-slo-a-rollback-and-2dd2
- Part 2: https://dev.to/rahimah_dev/a-reader-was-right-failing-fast-would-have-saved-my-users-azure-container-apps-part-2-3jc7
