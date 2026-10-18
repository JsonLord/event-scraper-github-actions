# R1.2 production activation controls

The staging workflow is `.github/workflows/fetch-strategy-probe.yml`, now named
**R1.2 read-only staging qualification**. Reusing its registered manual workflow
allows qualification on the PR branch without merging or dispatching another
workflow from a workflow. Its only trigger is `workflow_dispatch`, its only
repository permission is `contents: read`, checkout credentials are not retained,
and it has no production environment, data commit or Pages step. Dependencies,
browsers, datasets, overlays, screenshots and reports are stored below
`RUNNER_TEMP`; the source checkout is read-only during execution. There is a
20-minute job deadline and one shared 600-second network budget. Quotas cover
both discovery and verification: at most 40 HTTP attempts including robots,
redirects and retries, eight per host, 1.5 MB per response, 25 MB total, six Fetch
URLs and four Search calls. Tests use mock transports and never live providers.

## Merge consequences and gating

Before these changes, merging PR #33 would match the Pages workflow's `main`
push path filters (`scripts/**`, `data/**`, and its workflow file). The new
workflow definition is evaluated on that push, but both build and deployment
jobs now additionally require **manual `workflow_dispatch`**, branch `main`, and
repository variable `PAGES_DEPLOYMENT_ENABLED` exactly equal to lowercase `true`.
The merge push therefore cannot publish, even if that variable were pre-set.

The daily workflow's combined verification/persistence/deployment job requires
branch `main` **and both** repository variables `DAILY_VERIFICATION_ENABLED` and
`PAGES_DEPLOYMENT_ENABLED` exactly equal to `true`. An unset, false, misspelled or
non-lowercase variable is not authorization. Its cron can be registered by a
merge, but it performs no work unless these conditions pass. This PR does not
set either repository variable. The integration's attempt to inspect repository
variables returned HTTP 403, so actual current values are not claimed as known.
The staging job never reads them and cannot activate production.

Weekly Sunday 17:00 UTC discovery, its matrix, per-day horizon, recovery and
low-aggregate guard are preserved. The legacy weekly job still persists discovery
and scored JSON on `main`; this existing behavior is **not disabled by the daily
flag**. Its Pages configuration, artifact upload and deployment now require
`PAGES_DEPLOYMENT_ENABLED=true` on `main`. Thus a future merge does not immediately
scrape or publish, but subsequent weekly schedules can still update canonical data.
If approval requires *no* automatic data writes after merge, the owner must
pause the existing weekly workflow in repository settings before merging.
Neither the weekly workflow nor repository settings were changed at runtime.

## Owner-controlled release sequence — not executed

1. Review the qualification results and unresolved source/evidence failures.
2. Before merging, confirm the two variables are unset/false using authorized
   repository settings, and pause weekly discovery if a data-write freeze is needed.
3. Merge only with explicit approval. The merge push cannot deploy Pages.
4. For a separately approved manual Pages deployment, set only
   `PAGES_DEPLOYMENT_ENABLED=true` and dispatch the Pages workflow on `main`.
   While enabled, the existing weekly workflow can publish on its next schedule.
5. Enable daily verification only after separate approval by setting
   `DAILY_VERIFICATION_ENABLED=true` as well. Daily verification currently persists
   its overlay and deploys in the same job, avoiding the token-push trigger trap.
6. Roll back activation by setting either variable false; set the Pages variable
   false to prevent all three publishing paths. Reverting a flag does not undo
   a previously completed deployment. Re-enable weekly discovery separately if paused.

No merge, repository-variable update, production workflow dispatch, production
JSON write or Pages deployment is performed by qualification or these instructions.

## R1.3 qualification and first-release decision

See [R1.3 report](R13_QUALIFICATION_REPORT.md) and its three committed machine
summaries. The same read-only staging workflow now offers `r13` and `r13-final`
phases. Its authority, deadlines, temporary output rules and six-Fetch/four-Search
per-run caps are unchanged. R1.3 consumed 12 Fetch URLs, six Search calls and 27
direct attempts across three separate successful qualification runs. No flags or
production files were changed. Two Raus occurrences now verify, while listing
coverage and occurrence-bound pricing remain incomplete.

Recommendation: conditional technical GO for an explicitly approved fresh
Berlin Bühnen + ufaFabrik release; NO-GO for the full three-source release and
NO-GO for daily activation now. A temporary four-row staging build is not an
approved release artifact. Unknown Raus prices must not imply affordability.

Final merge-impact review: `.github/workflows/weekly-event-scraper.yml` still has
`contents: write`, Sunday `0 17 * * 0`, and `git add data/events.json
data/events_scored.json`, `git commit`, `git push` in aggregation. Neither daily
nor Pages flag prevents those legacy data writes. The next Sunday invocation on
18 October 2026 is 19:00 CEST (17:00 UTC); in winter it is 18:00 CET. This branch
has not changed the repository workflow's enabled/disabled state. An authorized
owner must inspect that state and pause weekly discovery before merge if the
release requires a complete automatic-write freeze. Merging alone does not
trigger that weekly scraper, but subsequent schedules or manual weekly dispatches
can write canonical data. A later true Pages flag can also permit weekly publishing.

The standalone Pages merge push remains unable to deploy because both jobs also
require manual dispatch. Daily verification still requires both explicit flags
and main. No additional publishing route or activation exemption was introduced.
Actual repository-variable values remain unverified (API read denied); absence
of a settings change by this PR must not be presented as proof of their values.
