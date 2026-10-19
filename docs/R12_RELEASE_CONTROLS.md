# Release controls — current after R1.4

This document now describes the stricter R1.4 controls. Earlier R1.2/R1.3
instructions that allowed an unqualified manual shared-data build are superseded.
See [R1.4 release candidate](R14_RELEASE_CANDIDATE.md) for evidence and the exact
owner-controlled activation/rollback sequence. Nothing was merged or activated.

## Read-only candidate qualification

`fetch-strategy-probe.yml` remains manual-only, `contents: read`, with no production
environment, data write/commit, Pages publishing or downstream dispatch. Its
`r14-pilot` phase uses fresh Berlin Bühnen and ufaFabrik discovery, the production
matcher/verifier, normalization/scoring and shared Pages builder. It stores its
candidate, observation overlay, static preview, checksums, manifest and sanitized
diagnostics only under runner temporary storage. No historical data fallback is
available. The artifact is `r14-pilot-release-candidate` with seven-day retention.

R1.2 limits remain: 20-minute job, shared 600-second network deadline, 40 direct
attempts/eight per host including robots/redirects/retries, 1.5 MB per response,
25 MB aggregate and six Fetch URLs/four Search calls. R1.4 uses zero Search calls.
The pilot requires exact known-venue matches and independent Berlin address
proof, future occurrences within calendar day +7, evidence age below six hours,
and at least two published occurrences on two dates per source. Unsupported
price/inventory stays UNKNOWN. Claims and candidate expire no later than six
hours or the earliest published performance start, including in the frontend.

## Publication authority and isolation

The standalone `jekyll-gh-pages.yml` now has **only `workflow_dispatch`**, required
candidate run ID and manifest digest inputs, and no production-data build fallback.
Both jobs require main, `PAGES_DEPLOYMENT_ENABLED=true` and
`RELEASE_PROFILE=berlin-ufa-pilot-v1`. It downloads the reviewed candidate from a
successful manual qualification run built from the exact same main SHA. The gate
checks profile/config, provenance, freshness, published identity/location coverage,
complete file checksums and a reproducible dataset rebuild. It verifies again
after the deployment-environment wait. Only the checked artifact's `site/` can
publish. The manifest records `authorization_to_release=false`: technical evidence
is never permission to publish.

The legacy weekly workflow's scrape, aggregation/data commits and Pages job all
require main, `RELEASE_PROFILE=unrestricted` and
`UNRESTRICTED_PUBLICATION_ENABLED=true`. Pages steps additionally retain the
original Pages flag. **Pilot activation cannot permit legacy automatic data writes
or publication.** This closes the R1.3 Sunday-write gap at the code level.

Daily verification retains both original flags (`DAILY_VERIFICATION_ENABLED=true`
and `PAGES_DEPLOYMENT_ENABLED=true`) and main, and now also requires the explicit
unrestricted profile/flag. It cannot replace a pilot with a broader dataset.
Unset, false, mismatched or incorrectly cased controls fail closed. A future
unrestricted release is a distinct owner decision, outside this pilot scope.

## Merge, transition and rollback

Merging does not publish: the standalone publisher has no push trigger. No flags
or runtime workflow states were changed by this PR. Actual current settings have
not been verified with the available permissions. Before a release, the owner must
inspect them, keep all production flags false/unset, and pause/cancel old weekly
and daily executions that may still use an earlier workflow revision. New guards
do not retroactively cancel previously admitted jobs.

The legacy Sunday trigger remains `0 17 * * 0` (18 October 2026: 19:00 CEST), but
its jobs now skip unless explicitly authorized for unrestricted operation. No
schedule was enabled or runtime state changed. Weekly source matrix and
unrestricted scraper behavior remain separate from pilot artifact production.

After an explicitly approved merge, generate/review a **new main-commit candidate**
and obtain separate publication approval. Set only the pilot profile and Pages
flag for the approved manual promotion; leave daily/unrestricted flags false and
schedules paused. PR-branch and expired candidates cannot be promoted.

For rollback, turn off production flags, cancel active publication jobs and keep
legacy schedules paused. Flags do not undo a completed deployment. An owner may
separately unpublish Pages if necessary, or approve a code rollback followed by a
fresh reviewed pilot build; stale historical datasets are not a rollback shortcut.
Exact commands and artifact review steps are in the R1.4 report.
