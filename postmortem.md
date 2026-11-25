# Postmortem: home page returned errors after the discount release

**Status:** resolved · **Severity:** high (home page down for all users) · **Blameless:** yes

## Summary
The "discount" release made the home page return HTTP 500 for every visitor. The health check stayed green, so nothing restarted the app. We rolled back with `git revert` and the pipeline redeployed the previous version.

## Timeline
| Time (UTC) | Event |
|------------|-------|
| 21:38 | Discount release pushed to main and deployed by the pipeline |
| 21:39 | check.sh / users report errors: 0/20 requests succeeded |
| 21:40 | Logs show `KeyError: 'DISCOUNT_PERCENT'` |
| 21:42 | `git revert` pushed; pipeline redeployed the previous version |
| 21:44 | check.sh: 20/20 requests succeeded. Incident resolved |

Time to restore: 3 minutes.

## Root cause
The new code read the `DISCOUNT_PERCENT` environment variable, which was never set in production. The error was caught and turned into a 500 for every request to the home page.

## Contributing factors
- No test exercised the home page with production-like settings.
- `/health` only checks that the process is running, not that the home page works.

## Action items
| Action | Owner | Status |
|--------|-------|--------|
| Read **required** settings once at startup with `os.environ["..."]` and fail fast; use `os.environ.get(..., default)` only for **optional** settings | me | ✅ done |
| Verify the new revision is Running and Healthy after deploy, in the pipeline | me | ✅ done |
| Smoke test `/` with `check.sh` after deploy, in the pipeline | me | ✅ done |
| Alert when the success rate drops below the SLO | me | open |

> **Correction:** the original action item was "read optional settings with a safe default". A reader pointed out that `DISCOUNT_PERCENT` was never optional: a default would have hidden the bug instead of fixing it.

## Follow-up: re-running the drill with fail-fast config
The same bug was shipped again with `DISCOUNT_PERCENT` read at startup.

- The new revision crashed in 0.3 s (`exit code 1`), was retried 5 times with backoff, then marked **Failed**.
- Azure Container Apps (single revision mode) kept 100% of traffic on the previous revision: `check.sh` stayed at **20/20**.
- The original pipeline still went green. The new **verify revision** step turned it red in 26 s.
- Setting `DISCOUNT_PERCENT=20` produced a healthy revision, and the discount went live with no user impact.
