# RunIt App - Ship, Break and Recover

[![deploy](https://github.com/rahimahisah17/runit-app/actions/workflows/deploy.yml/badge.svg)](https://github.com/rahimahisah17/runit-app/actions/workflows/deploy.yml)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-container-2496ED?logo=docker&logoColor=white)
![Azure Container Apps](https://img.shields.io/badge/Azure-Container%20Apps-0078D4?logo=microsoftazure&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/CI%2FCD-GitHub%20Actions-2088FF?logo=githubactions&logoColor=white)

A small Python web app, containerised with Docker and deployed to **Azure Container Apps** by a **GitHub Actions** pipeline on every push to `main`. It's run with the basics of reliability engineering: a health check, an SLO, a one-command rollback and a blameless postmortem.

This repo is the result of an **incident drill**. I shipped a bad release on purpose, detected it, rolled back in **3 minutes 22 seconds**, and wrote it up.

> Built as part of the *RunIt Weekend: Ship, Break and Recover an App* lab.

---

## Table of contents

- [Architecture](#architecture)
- [Repository structure](#repository-structure)
- [The app](#the-app)
- [Reliability](#reliability)
- [Run locally](#run-locally)
- [Deploy](#deploy)
- [Roll back](#roll-back)
- [Incident drill](#incident-drill)
- [Lessons learned and next steps](#lessons-learned-and-next-steps)
- [Clean up](#clean-up)
- [Author](#author)

---

## Architecture

```
 git push (main)
      │
      ▼
 GitHub Actions ──► build image ──► push to GHCR (tag = commit SHA)
      │                                     │
      └──► az login (service principal) ──► az containerapp update
                                            │
                                            ▼
                                  Azure Container Apps ──► users
                                            │
                                            ▼
                                   Log Analytics (logs)
```

| Component | Purpose |
|---|---|
| **Python app** (standard library only) | Serves the home page and a `/health` endpoint |
| **Docker** | Packages the app; runs as non-root with a `HEALTHCHECK` |
| **GitHub Container Registry (GHCR)** | Stores images, each tagged with the commit SHA |
| **GitHub Actions** | Builds, pushes and deploys on every push to `main` |
| **Azure Container Apps** | Runs the container with external HTTPS ingress |
| **Log Analytics** | Collects container logs used to diagnose incidents |
| **Service principal** | Pipeline identity, scoped to the `runit-rg` resource group only (least privilege) |

---

## Repository structure

```
runit-app/
├── .github/
│   └── workflows/
│       └── deploy.yml      # CI/CD pipeline: build → push → deploy
├── app.py                  # The web app (/ and /health)
├── Dockerfile              # Container image with HEALTHCHECK, non-root user
├── check.sh                # Quick SLO check: 20 requests to the home page
├── postmortem.md           # Blameless postmortem of the incident drill
└── README.md
```

---

## The app

| Endpoint | Response | Purpose |
|---|---|---|
| `GET /` | `200` HTML home page | What users see |
| `GET /health` | `200` `{"status": "ok"}` | Liveness: the process is running |

Errors on the home page are caught, logged with the request path and returned as a clean `500`, so one bad request never takes the process down.

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

19/20 or better means we're within the SLO.

### Health check

`GET /health` returns `{"status": "ok"}` while the process is running. The Dockerfile's `HEALTHCHECK` uses it, so the platform can restart a dead container.

> ⚠️ **A health check is not an SLO.** `/health` proves the process is alive, not that users get a working page. The incident drill below is the proof.

---

## Run locally

**Prerequisites:** Docker.

```bash
# Build the image
docker build -t runit-app:good .

# Run it
docker run -d -p 8080:8080 --name runit runit-app:good

# Check health and the SLO
curl -s localhost:8080/health; echo
bash check.sh

# Stop it
docker rm -f runit
```

---

## Deploy

Every push to `main` deploys automatically through [`.github/workflows/deploy.yml`](.github/workflows/deploy.yml):

1. Check out the code.
2. Log in to GHCR with the built-in `GITHUB_TOKEN`.
3. Build and push `ghcr.io/<owner>/runit-app:<short-sha>`.
4. Log in to Azure with the `AZURE_CREDENTIALS` secret.
5. Run `az containerapp update` to roll out the new image.

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
```

**3. Give the pipeline access to Azure**

```bash
SUB_ID=$(az account show --query id -o tsv)
az ad sp create-for-rbac --name runit-github --role contributor \
  --scopes /subscriptions/$SUB_ID/resourceGroups/runit-rg --json-auth
```

Save the JSON output as a repository secret named **`AZURE_CREDENTIALS`** (Settings → Secrets and variables → Actions).

### Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Pipeline fails with `permission_denied: write_package` | The repo's Actions token can't write to a package that was first pushed manually | Package settings → **Manage Actions access** → add `runit-app` with **Write** |
| `az containerapp up` stays on "Running" after creating the environment | The CLI stopped polling, even though Azure finished | Check `az containerapp env show ... --query properties.provisioningState`; if `Succeeded`, cancel and re-run, and it reuses the environment |
| `az extension add` hangs on "Searching" | Network or DNS hiccup fetching the extension index (seen in WSL) | Check `az extension show --name containerapp`; skip if already installed |

---

## Roll back

Rollback is just another commit. It goes through the same pipeline as every other change:

```bash
git revert --no-edit <bad-commit>
git push
```

`git revert` keeps history intact, so there's nothing special to run and nothing is deleted.

---

## Incident drill

I shipped a "discount" feature that read a `DISCOUNT_PERCENT` environment variable that was never set in production.

| | Result |
|---|---|
| Pipeline | ✅ green |
| `/health` | ✅ `{"status": "ok"}` |
| `check.sh` | ❌ **0/20 requests succeeded, SLO broken** |
| Logs | `ERROR serving /: KeyError('DISCOUNT_PERCENT')` |
| Fix | `git revert` + push |
| **Time to restore** | **3 minutes 22 seconds** |

Full write-up, with timeline, root cause, contributing factors and action items: **[postmortem.md](postmortem.md)**

---

## Lessons learned and next steps

- **Green doesn't mean working.** The pipeline and the health check were both green while 0% of users could load the page. Measure the path users actually take.
- **Fail fast on required config.** A missing *required* setting should stop the process at startup, not fail on every request. On Azure Container Apps (single revision mode), a new revision that never becomes ready doesn't receive traffic, so users would have stayed on the working version with no rollback needed. Optional settings should use `os.environ.get(..., default)`.
- **Make rollback boring.** The normal deploy path is the rollback path.

**Planned improvements:**
- [ ] Read required settings at startup and fail fast; use safe defaults only for optional ones
- [ ] Add a smoke test that requests `/` in the pipeline before deploying
- [ ] Alert when the success rate drops below the SLO
- [ ] Re-run the drill with fail-fast config and compare the results

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
- Read the full write-up on DEV: https://dev.to/rahimah_dev/ship-it-break-it-fix-it-running-a-python-app-on-azure-container-apps-with-an-slo-a-rollback-and-2dd2
