# R1.4 — isolated Berlin Bühnen + ufaFabrik pilot

**Technical GO for this bounded pilot; no authorization to release.** PR #33 stays
in draft. Nothing was merged, deployed or activated. Production discovery/scored
JSON and the production observation overlay are unchanged. No repository variable
or workflow enabled/disabled state was changed.

This supersedes the conditional pilot recommendation in
[R1.3 qualification](R13_QUALIFICATION_REPORT.md). The full three-source release
and daily activation remain outside this approval scope.

## Reviewable candidate artifact

Latest qualified run: [39094611434](https://github.com/JsonLord/event-scraper-github-actions/actions/runs/39094611434).

- [Download/review artifact 12123753898](https://github.com/JsonLord/event-scraper-github-actions/actions/runs/39094611434/artifacts/12123753898): **r14-pilot-release-candidate**, 242860 bytes, seven-day retention.
- Build commit: `c1a153b934433288694aa7c78b7934b76472b7dd`.
- Manifest SHA-256: `8c3d4d9e3c97dcf22763ff356a39a508f38489b5453628567ee05aaa57c326cd`.
- GitHub artifact archive digest: `174539e75ce04c45a64ec2d04f34ecb914d71ff7919638f8654d21f4c943e3e9`.
- Discovery/build timestamp: 18 October 2026 **05:44:01 CEST** (03:44:01 UTC).
- Evidence expiry: 18 October 2026 **11:44:01 CEST** (09:44:01 UTC). A new candidate can expire earlier if its earliest published performance starts sooner.

The artifact contains `site/index.html`, `site/events_scored.json`, `.nojekyll`,
`release-manifest.json`, fresh discovery input, timestamped overlay, diagnostics,
desktop/mobile screenshots, rendered HTML, browser report and an exported ICS.
Only metadata and qualification evidence are committed in
[r14-candidate-evidence.json](r14-candidate-evidence.json); generated release datasets
and site files remain exclusively in Actions artifacts/temporary runner storage.

Extract the artifact and serve its `site` directory locally to inspect the static
preview, or review `smoke/desktop.png` and `smoke/mobile.png`. This is an artifact
preview, not a published site. Artifact download in the managed development
environment was unavailable; the Actions candidate job itself validated every
file checksum and rebuilt the dataset before uploading. Sanitized check annotations
provided the committed evidence metadata without exposing signed download URLs.

**This PR-branch artifact cannot be promoted to production.** Publication requires
a fresh successful candidate run from the exact current `main` commit. Rebuild
after the owner approves and merges; do not reuse this artifact's run/hash for that
future dispatch. Expired artifacts remain historical evidence only.

## Explicit release profile and fresh inputs

`config/pilot_release.json` fixes profile `berlin-ufa-pilot-v1` to the exact
Berlin Bühnen and ufaFabrik listing URLs. A missing, alternate or lookalike source
is a configuration failure, not silently accepted or filtered into this profile.
Rausgegangen and every other source are excluded. The candidate entry point has
no historical-file input or frozen-data fallback: it performs fresh bounded
public discovery on Berlin's current date and day +7, plus ufaFabrik's live listing.

Every published occurrence must have:

1. An exact official event URL and known start time, after the current Berlin
   clock and no later than calendar day +7.
2. Discovery and a strict title/date/time/venue match no older than six hours.
3. Independent, fresh Berlin location evidence bound to that venue: the Berlin
   detail's `Ort` block with matching venue/postal Berlin address, or a matched
   ufaFabrik campus room plus the freshly fetched official campus address.
   The permitted campus rooms are Theatersaal, Wolfgang Neuss Salon and Varieté
   Salon. An artist's city, event title or generic organizer prose is insufficient.
4. Fresh overlay evidence for any asserted price, discount or status. Listing/body
   text cannot recreate unsupported claims during normalization/scoring. UNKNOWN
   stays UNKNOWN; cancellation/postponement excludes the occurrence.

The shared production normalization, exact matcher/verifier, overlay merger,
scoring and Pages `build()` function are reused. The pilot wrapper restricts
inputs, supplies only verified claims, then checks every materialized row. It
cannot relax the production builder into an unrestricted pilot publication.
A technical GO also requires at least two published occurrences on at least two
dates **for each source**. An empty, partial or single-date qualification remains
NO-GO, even when every selected event matched.

The candidate and every claim expire at the earlier of six hours from discovery
or the earliest published performance start. The browser respects that cap:
expired prices/student labels, inventory, event states and verified-link labels
are hidden or become UNKNOWN/Check site. Price sorting no longer treats expired
prices as cheap. An already open preview rerenders at expiry; expired ICS exports
omit descriptive claims and point readers to the official event page. Existing
search, categories, past-event control, responsive tables and ICS remain available.

## Exact publication coverage and event evidence

Fresh discovery found **55 occurrences**: 48 Berlin Bühnen and seven ufaFabrik.
The bounded verifier selected six (three per source), and the pipeline published
**five**: two Berlin Bühnen and three ufaFabrik. One freshly matched cancelled
occurrence was rejected; 49 unselected occurrences had no fresh detail/location
proof and were excluded. Their rejection label is “Missing Berlin venue evidence”;
this does not claim the source has 49 blank venue fields. It records the absence
of release-grade proof for rows not inspected within this small pilot's budget.

| Measure | Berlin Bühnen | ufaFabrik | Total |
|---|---:|---:|---:|
| Discovered occurrences | 48 | 7 | 55 |
| Verification targets | 3 | 3 | 6 |
| Published exact matches | 2 | 3 | 5 |
| Published rows | 2 | 3 | 5 |
| Exact publication coverage | 2/2 (100%) | 3/3 (100%) | 5/5 (100%) |
| Discovery-to-publication coverage | 2/48 (4.17%) | 3/7 (42.86%) | 5/55 (9.09%) |
| Distinct published dates | 18 and 25 October | 18 and 19 October | 3 |

This is a deliberately small, fully verified publication candidate, not complete
source coverage. No generic venue/listing link substitutes for an event URL.
All five rows have matching nonblank venues and fresh Berlin location evidence;
zero published rows have missing event links, missing venues or unmatched identity.

| Published occurrence (Berlin time) | Venue | Confirmed pricing | Ticket inventory |
|---|---|---|---|
| Helga Schubert: Die Woche danach — 18 Oct, 13:00 | Berliner Ensemble | UNKNOWN | UNKNOWN |
| Ella Carina Werner — 18 Oct, 19:00 | Wolfgang Neuss Salon | €12–22; explicit student tier/conditions | UNKNOWN |
| Live-Hörspiel “Schöneberger Allerlei – Fall 4” — 18 Oct, 19:00 | Theatersaal | €12–26; explicit student tier/conditions | UNKNOWN |
| Magic Monday Leipzig — 19 Oct, 20:00 | Varieté Salon | €12–22; explicit student tier/conditions | UNKNOWN |
| Lesung: “Die Einstein-Protokolle” — 25 Oct, 11:00 | Deutsches Theater Berlin | UNKNOWN | UNKNOWN |

The three price ranges include conditional student offers, not a promise that
regular admission costs €12. No free admission or live ticket availability was
confirmed. Both Berlin rows have fresh scheduled event-state evidence; ufa event
state remains UNKNOWN. “Magic Monday Leipzig” is correctly located in Berlin
through its actual ufaFabrik venue/address, not inferred from the title.

## Reproducibility, budgets and qualification

The read-only manual workflow remains `fetch-strategy-probe.yml`, with phase
`r14-pilot`. Permission remains only `contents: read`, no production environment,
commit, deployment, scheduling or downstream dispatch. Outputs and dependency/
browser installations are under `RUNNER_TEMP`. Hidden-file artifact inclusion
preserves `.nojekyll`. The same 20-minute job and 600-second network deadlines,
40 HTTP attempts/eight per host/25 MB total limits and six-Fetch cap apply;
R1.4 disables Search entirely.

| Run | Purpose | Direct attempts | Fetch / Search | Response bytes | Pipeline seconds |
|---|---|---:|---:|---:|---:|
| [39094362722](https://github.com/JsonLord/event-scraper-github-actions/actions/runs/39094362722) | Initial pilot and manifest guards | 14 | 3 / 0 | 1056712 | 32.143 |
| [39094611434](https://github.com/JsonLord/event-scraper-github-actions/actions/runs/39094611434) | Final URL/expiry and browser qualification | 14 | 3 / 0 | 1056712 | 28.702 |

Both runs succeeded, with eight Berlin-host and six ufa-host direct attempts per
run (including robots/redirects), all provider Fetch envelopes HTTP 200 and schema
valid, and no observed provider quota/auth/rate errors. Aggregate R1.4 use is 28
direct attempts and six Fetch URLs, zero Search calls. Repeated runs reuse the
same occurrences; totals are not added as unique events. No paid endpoints,
challenge bypass, login or circumvention proxy was used.

Every file except the manifest itself has a SHA-256 in the manifest; the manifest
has its separately reviewed digest. The gate verifies source/profile/config hash,
run ID, exact commit, expiry, complete file set, symlink/path safety and checksums.
It rebuilds the Pages dataset from included inputs with the recorded timestamp,
compares exact JSON, checks the frontend bytes against the checkout, recomputes
quality metrics and requires passing browser qualification. Missing, mismatched,
tampered, expired, single-date and NO-GO manifests cannot publish. A second verifier
execution five minutes later selected zero targets and preserved the overlay.

Final checks: **252 Python tests passed**, preserving the prior 226-test suite;
Node syntax/Berlin clock/category-search/expiry checks passed; checksum-verified
actionlint passed; frozen audit/shared build/schema and zero-network verifier dry
run passed. Frozen browser smoke retained 112 upcoming/464 total rows, category
search, ICS and responsive rendering without JS errors. Final candidate Chromium
qualification also passed category search, ICS, responsive rendering and simulated
post-expiry masking. The strict validator requires those passing candidate results.
CI runs on the follow-up commits; no tests call live paid services.

## Publication isolation and merge consequences

The standalone Pages workflow now has **manual dispatch only**. It never builds
from `data/events*.json`. Both jobs require `main`, `PAGES_DEPLOYMENT_ENABLED=true`
and `RELEASE_PROFILE=berlin-ufa-pilot-v1`. Required inputs pin the successful
candidate run and reviewed manifest digest. Provenance checks require a successful
manual candidate workflow run from the same exact `main` SHA. Only that candidate's
validated `site/` directory becomes the Pages artifact. The deployment job repeats
validation after its `github-pages` environment wait, so delayed approval cannot
promote expired evidence.

Weekly scrape, aggregation/data commits and Pages publishing now additionally
require `RELEASE_PROFILE=unrestricted` **and**
`UNRESTRICTED_PUBLICATION_ENABLED=true`. Daily verification requires those same
two unrestricted controls plus both original daily/Pages flags. Consequently,
enabling pilot Pages cannot authorize either workflow to overwrite the pilot or
write broader canonical data. An unset or misspelled profile/flag fails closed.
This tightens the R1.3 warning: legacy Sunday writes are now code-gated, rather
than relying only on the owner pausing the workflow. No weekly source matrix or
unrestricted algorithm was expanded; these are authority guards.

A merge does not deploy or activate the pilot. It installs the new guards;
previously queued/running workflows may still use the old revision and must be
handled by the owner before activation. Runtime flags and workflow state were not
changed or inferred. Their actual values remain for an authorized owner to inspect.

## Owner-controlled activation — NOT EXECUTED

1. **Approve code/merge separately.** Review this PR and artifact. Inspect actual
   repository variables and Pages environment protections. Keep Pages, daily and
   unrestricted flags false/unset. Pause legacy weekly/daily workflows and cancel
   queued/running legacy production jobs before merging, so old workflow revisions
   cannot race the pilot. These owner actions have not been performed here.
2. After explicit merge approval, merge the PR on `main`. Keep production flags
   off. The merge cannot publish; the standalone publisher has no push trigger.
3. Build fresh evidence from the exact current main revision:

   ```sh
   gh workflow run fetch-strategy-probe.yml --ref main -f phase=r14-pilot
   ```

   Wait for success. Download its **r14-pilot-release-candidate** artifact. If it
   reports technical NO-GO, stop; do not loosen the profile or substitute frozen data.
4. Inspect the bounded preview (up to six published rows), all published identities,
   dates/venues, UNKNOWN claims, price eligibility, screenshots, ICS and diagnostics.
   Read the new manifest's actual source counts, dates, expiry, run ID and full
   commit SHA. Record its SHA-256 as the exact content being approved. Validate
   offline from that checkout before approval:

   ```sh
   python scripts/pilot_release.py --artifact "$CANDIDATE_DIRECTORY" \
     --manifest-sha256 "$MANIFEST_SHA256" --commit "$FULL_MAIN_SHA" \
     --run-id "$CANDIDATE_RUN_ID"
   ```

   `CANDIDATE_DIRECTORY` is the extracted artifact root. Use values from the **new
   main run**, not the PR preview values above. The main SHA must still be current;
   if code changes or evidence expires, rebuild and review again.
5. **Only after explicit authorization to publish that exact manifest**, set:

   ```text
   RELEASE_PROFILE=berlin-ufa-pilot-v1
   PAGES_DEPLOYMENT_ENABLED=true
   DAILY_VERIFICATION_ENABLED=false
   UNRESTRICTED_PUBLICATION_ENABLED=false
   ```

   Leave schedules paused and require the desired owner approval on the
   `github-pages` environment. Then manually dispatch:

   ```sh
   gh workflow run jekyll-gh-pages.yml --ref main \
     -f candidate_run_id="$CANDIDATE_RUN_ID" \
     -f manifest_sha256="$MANIFEST_SHA256"
   ```

   Missing provenance, source mismatch, modified files, expired claims or a changed
   main commit stop publication. This workflow cannot fall back to production JSON.
6. Check the deployment's actual manifest/run, source counts, live search/ICS and
   expiry behavior. Set Pages back to false after the approved manual publication
   to prevent additional dispatches; this does not remove the deployed site.
   Keep daily/unrestricted controls false. A pilot update needs another fresh,
   separately reviewed artifact and explicit publication decision.

## Owner-controlled rollback — NOT EXECUTED

1. Set `PAGES_DEPLOYMENT_ENABLED=false`, `DAILY_VERIFICATION_ENABLED=false` and
   `UNRESTRICTED_PUBLICATION_ENABLED=false`; keep the pilot profile selected.
   Cancel queued/running publication jobs and keep legacy schedules paused.
   Changing a flag alone does not cancel a job already admitted or undo a deployment.
2. Inspect the last completed Pages deployment. If serving it must stop immediately,
   the owner can explicitly unpublish the site in Pages settings. No such action
   is taken by this PR. The frontend independently masks expired pilot claims.
3. To restore an earlier approved code version, separately approve/revert code on
   main, build a **fresh** pilot candidate from that exact main SHA, review its new
   manifest and follow the manual sequence above. An old expired artifact is not
   a valid rollback dataset. Do not enable an unrestricted workflow or restore the
   historical October 11 snapshot as a shortcut.

**Technical qualification is GO; authorization to merge, publish or schedule is
not granted and has not been exercised.**
