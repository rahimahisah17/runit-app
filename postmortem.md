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
| Action | Owner | Due |
|--------|-------|-----|
| Read optional settings with a safe default (`os.environ.get`) | me | next release |
| Add a test that requests `/` before deploy, in the pipeline | me | this week |
| Alert when the success rate drops below the SLO | me | this week |
