# R1.2 — end-to-end qualification, no production deployment

Review date: **2026-10-18 Europe/Berlin**. Qualification observations were recorded
on October 18 at approximately 00:37–00:45 Berlin time (October 17 22:37–22:45 UTC).
This report distinguishes successful transport, discovered candidates, matched
occurrences and published data. No production data was changed or published.

## Execution and evidence

The existing registered manual workflow `fetch-strategy-probe.yml` was converted
to **R1.2 read-only staging qualification**. This avoided merging to register a new
workflow. Its only trigger is `workflow_dispatch`, and its only repository
permission is `contents: read`. It does not retain checkout credentials, use a
production environment, commit, push, merge, deploy, upload a Pages artifact or
dispatch another workflow. Generated files, Python environment, browser binaries,
working overlays and artifacts are under `RUNNER_TEMP`; checkout cleanliness and
production-file SHA-256 checks passed in every run.

The harness reuses production `scrape_document`, `validate_events`, verifier
`run`/`observation`, `build_page_dataset.py` and the frontend/ICS smoke runner.
It has no alternative event-verification algorithm. A shared bounded HTTP client
and TinyFish client cover discovery **and** verification. Completion phases were
limited to the remaining allowance rather than repeating the six matched events.

| Run / committed evidence | Scope | Result |
|---|---|---|
| [39075788276](https://github.com/JsonLord/event-scraper-github-actions/actions/runs/39075788276) · [phase 1](r12-qualification-phase1.json) | All three listings, six selected events | Pipeline and browser smoke passed; Rausgegangen yielded no rows |
| [39076025613](https://github.com/JsonLord/event-scraper-github-actions/actions/runs/39076025613) · [phase 2](r12-qualification-phase2.json) | Rausgegangen listing with full production geography/date parameters | Fetch succeeded, but no event titles/links could be extracted |
| [39076254478](https://github.com/JsonLord/event-scraper-github-actions/actions/runs/39076254478) · [phase 3](r12-qualification-phase3.json) | Two Search queries and one fetched Rausgegangen candidate | One current candidate discovered; verification remained UNKNOWN at the source-host/request budget |
| [bounded direct diagnosis](r12-raus-direct-diagnosis.json) | Rausgegangen robots + listing only | Two direct attempts, listing HTTP 403; no provider requests |

All three staging workflows completed successfully and uploaded sanitized
`r12-sanitized-staging-diagnostics` artifacts. Phase 1's artifact is
[12117056763](https://github.com/JsonLord/event-scraper-github-actions/actions/runs/39075788276/artifacts/12117056763),
248,959 bytes, SHA-256
`744511b4eb083b88d2667b28612a9516fde8475fe30a81e0945f1414be8fe1c3`.
It includes the temporary discovery sample, first/second overlays, expired
materialization, shared static dataset, rendered HTML, desktop/mobile screenshots,
ICS download, full HTTP/provider diagnostics and reports. The compact JSON evidence
committed here was recovered losslessly from complete check-annotation chunks;
no further provider requests were used to retrieve it.

## Current sample and matching

| Source | Discovered in sampled date window | Selected | Verified | Missing candidate links / venues in selected rows |
|---|---:|---:|---:|---:|
| Berlin Bühnen | 48 across two dated listings | 3 | 3 | 0 / 0 |
| ufaFabrik | 7 | 3 | 3 | 0 / 0 |
| Rausgegangen | 1 fetched Search candidate; listings yielded 0 | 1 | 0 | 0 / 0, with identity/location still unverified |
| Total | 56 observed rows/candidates | 7 | 6 | 0 / 0 |

**Exact matching success is 6/7 = 85.7% of selected candidates.** The first cohort
was 6/6; it is not reported as 100% three-source coverage. Rausgegangen is represented
by a current fetched candidate, not a verified Berlin occurrence. Search query
geography is not destination-location proof. Zero missing venues in this tiny
sample does not establish general venue completeness, and zero parsed listing
rows is not evidence that Rausgegangen has no events.

The six matched occurrences were:

| Occurrence | Confirmed admission evidence | Discount/status evidence |
|---|---|---|
| Helga Schubert: Die Woche danach · Oct 18 13:00 | UNKNOWN | Scheduled source state; inventory UNKNOWN |
| Es war einmal ein Zaubersmann · Oct 25 11:00 | UNKNOWN | Explicitly cancelled selected occurrence; inventory UNKNOWN |
| Historische Führung · Oct 25 12:00 | €8 | Scheduled source state; inventory UNKNOWN |
| Ella Carina Werner · Oct 18 19:00 | €12–€22 | Explicit student offer detected; inventory UNKNOWN |
| Live-Hörspiel „Schöneberger Allerlei – Fall 4“ · Oct 18 19:00 | €12–€26 | Explicit student offer detected; inventory UNKNOWN |
| Magic Monday Leipzig · Oct 19 20:00 | €12–€22 | Explicit student offer detected; inventory UNKNOWN |

Four occurrences gained detail-price evidence and three gained explicit student
eligibility evidence. The table gives admission ranges; complete offer amounts
and conditions are in the uploaded overlay, not inferred from a Search snippet.
No occurrence was confirmed Free or available. No sold-out state was independently
confirmed from these detail observations. That coverage gap is distinct from the
passing sold-out fixture regressions. The cancelled occurrence was real source
state; no ticket inventory was inferred from its ticket button.

The remaining candidate, **Gavin DeGraw · Oct 18 20:00**, stayed UNKNOWN. It was
not counted as verified, was not used to assert availability, and produced no
frontend row after the shared builder's existing preference rules. Its precise
filter reason was not included in the compact report. The latest code additionally
requires destination-field Berlin evidence for future Search-derived discovery;
this additional guard was unit-tested, not live requalified.

## Identity, overlay, freshness and frontend

- The live verifier matched exact title, occurrence date/time and venue for the
  six successful rows. Their distinct SHA-256 occurrence IDs and match bases are
  recorded in phase 1 evidence. The Oct 25 cancellation is not the Oct 18 show.
- Two fetched detail pages contained five and nine performance rows. The five-row
  page's selected Oct 25 occurrence was correctly cancelled; the nine-row page's
  selected occurrence was scheduled. The original diagnostic name
  `contains_other_cancellation` only indicated an `Abgesagt` marker somewhere in
  the section; it did not independently prove a *different* row was cancelled.
  The latest code renames that diagnostic to `contains_cancellation_marker`.
- Separate real-response regression tests select Oct 18 from the same production
  page and prove that the Oct 25 cancellation does not contaminate it. No live
  status is assigned using generic page keywords or nearby event cards.
- Counterfactual missing-venue replay against the live fetched content matched
  **3/6** using official canonical occurrence identity; the other three correctly
  stayed UNKNOWN. They are simulations of absent input, not additional live events.
  A later unit-tested normalization accepts official `www` aliases only with the
  same path and matching occurrence; the recorded 3/6 result is not rewritten.
- Each live cohort ran the production verifier again at simulated +5 minutes.
  Fresh targets selected: **0**. Observations were unchanged and counters proved
  **zero additional HTTP, Fetch or Search calls**. First/second sanitized overlays
  were saved as separate artifact files.
- Building at simulated +8 days/+1 hour expired verification/price/free assertions
  and left historical overlay evidence intact. No expired observation asserted
  availability. Discovery input and overlay immutability assertions passed.
- The current harness also writes/reloads a temporary working overlay before the
  second run; this disk round-trip is covered by the offline integration test
  using real captures. That small post-run improvement was not live requalified.
- The production CLI built five frontend records from the first cohort's six
  observations, preserving the existing preference exclusions and price cutoff.
  It did not invent a row to make the browser test pass. Chromium displayed five
  upcoming rows, search worked, a real ICS download passed, desktop/mobile rendering
  passed, and JavaScript reported zero errors. JSON/quality gates passed as well.
- Empty Rausgegangen completion datasets passed structural/UNKNOWN checks but
  explicitly reported browser smoke **not run**, rather than claiming a passing
  zero-row functional test. Frontend functional evidence comes from phase 1.

## Exact usage and budgets

| Resource | Actual combined qualification usage | Ceiling |
|---|---:|---:|
| TinyFish Fetch URLs | **6** = 4 + 1 + 1 | 6 |
| TinyFish Search calls | **2** = 0 + 0 + 2 | 4 |
| Direct HTTP attempts, including diagnosis | **21** = 15 + 2 + 2 + 2 | 40 |
| Berlin Bühnen direct attempts | 8 | 8 per host |
| ufaFabrik direct attempts | 5 | 8 per host |
| Rausgegangen direct attempts, all phases + diagnosis | 8 | 8 per host |
| Response bytes accounted by the clients | **1,036,862** | 25,000,000 total; 1,500,000 per URL |

All six Fetch responses and both Search responses were HTTP 200 with validated
response envelopes and no reported per-URL error. Fetch call durations were
6.489, 4.324, 1.509, 0.772, 6.793 and 2.432 seconds. Search calls took 0.927 and
1.645 seconds. Network phases lasted 25.813, 7.045 and 5.499 seconds; the first
complete pipeline including the browser smoke took 44.965 seconds. Workflow job
durations were 83, 48 and 65 seconds, including isolated dependency/browser setup,
below each 20-minute job deadline. Each phase had a shared 600-second network
wall budget; no phase extended an exhausted request/host/provider quota.

Fetch used semantic HTML, `ttl: 0`, a 45-second per-URL backend deadline and an
8/150-second client connect/read timeout. Direct HTTP used 8/12 seconds, bounded
responses, robots checks, and counted redirects/retries. Processing was sequential,
below the two-in-flight ceiling. Only free-allowance Fetch/Search endpoints were
used; no paid Agent/Browser, wallet funding, proxy purchase or challenge-solving
flow was invoked. No further Fetch qualification was attempted after the six-URL
allowance was consumed. Diagnostics contain no keys or sensitive URL parameters.

## Remaining errors by category

| Category | Evidence and effect |
|---|---|
| Extraction / representation | Rausgegangen's fetched listing retained dates, venue/price fragments but had **no headings or event links**. Production extraction refused to manufacture titles or associate adjacent prices. Correct geography parameters did not restore the missing relationships. |
| Provider / source access | Rausgegangen direct listing access returned HTTP 403. TinyFish's REST transport succeeded; this was not a 401/402/429 or malformed-provider-response failure. Successful transport did not make the bleached listing useful event evidence. |
| Missing source evidence | Two matched Berlin Bühnen prices and all selected live ticket inventories remained UNKNOWN. Sold-out detail coverage was not demonstrated. Three missing-venue replays were unresolved. |
| Workflow / integration budget | The Search-derived candidate could not complete its next detail/canonical verification within the remaining host/request budget. The verifier preserved UNKNOWN instead of re-fetching beyond the caps. Exact/final URL caching has since been tightened offline, but this is not recorded as a successful live retry. |
| Operational release | Repository-variable inspection was denied (403). The operator must confirm settings before merge/activation. No production-write or deployment permission was needed to qualify staging. |

## Frozen versus current evidence

The October 11 fixture remains unchanged: 475 rows, with the existing audit
normalizing to 464 after nine quarantines and two duplicate merges. Its prices,
venues and links are historical extraction evidence, not current inventory.
R1.2 instead used upcoming Oct 18–25 occurrences discovered at execution time.
The cohorts and denominators differ, so 6/7 matching or zero sample venue gaps
must not be presented as a retrospective percentage improvement over the frozen
475 rows. Real new evidence includes three current student-offer observations,
a selected cancellation and the end-to-end overlay/build/expiry/browser checks.

## Release decisions

| Gate | GO / NO-GO | Scope |
|---|---|---|
| Source coverage | **NO-GO for broad release** | All three sources were attempted and seven current candidates observed, but only two sources yielded verified occurrences. Rausgegangen listing relationships and its unverified candidate remain unresolved. |
| Daily verifier integration | **GO for the exercised staging contract** | Real discovery → production verifier → timestamped overlay → second run → shared CLI build → expiry → frontend/ICS passed. This is not approval to activate the production job. |
| Data correctness | **GO for evidence/uncertainty handling** | 6/7 exact selected-candidate matches; unsupported prices/inventory/location remain UNKNOWN. No fabricated data, expired availability or cross-performance cancellation claim was introduced. Broader source accuracy is not claimed. |
| Safe schedule activation controls | **GO for fail-closed controls; activation withheld** | Daily requires both flags; Pages publishing is gated. No flag was changed. Operator settings and outstanding source coverage must be reviewed before enabling. |
| Pages deployment readiness | **NO-GO for production release** | The static pipeline is functionally qualified, but source coverage and explicit deployment approval remain outstanding. No merge or deployment occurred. |

See [R12_RELEASE_CONTROLS.md](R12_RELEASE_CONTROLS.md) for exact merge consequences
and owner-controlled activation. The `main` merge push can create a skipped Pages
workflow run but cannot publish because its jobs now require a manual dispatch
plus the Pages flag. Legacy weekly discovery/data commits are still scheduled;
the owner must pause that existing workflow before merge if a complete production
data-write freeze is required. The daily flag alone does not stop legacy weekly
commits. No runtime configuration, flag, scheduling or production environment
was activated by this work.
