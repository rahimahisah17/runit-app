# RunIt app: shipped, measured and recovered (RunIt Weekend)

A small Python web app, containerised with Docker, deployed by a GitHub Actions pipeline, and run with the basics of reliability engineering.

## Live app
https://runit-app.delightfulpebble-d7a8abc4.westeurope.azurecontainerapps.io

## Architecture
GitHub push → GitHub Actions (build image, push to GitHub Container Registry, deploy) → Azure Container Apps → users.

## SLO
**99.5% of requests to the home page succeed (HTTP 200), measured over 30 days.** That error budget is about 3.6 hours a month. `check.sh` gives a quick reading: 19/20 or better means we are within the SLO.

## Health check
`GET /health` returns `{"status": "ok"}` while the process is running. The Dockerfile's HEALTHCHECK uses it so the platform can restart a dead container.

## How to deploy
Push to `main`. The workflow in `.github/workflows/deploy.yml` builds, pushes and deploys. To roll back: `git revert <bad commit>` and push.

## Incident drill
I shipped a bad release on purpose, detected it with `check.sh` and the logs, rolled back, and wrote [postmortem.md](postmortem.md). Time to restore: 3 minutes.
