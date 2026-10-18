# R1 review: evidence quality and bounded verification

This branch implements the four requested commit groups. It is **not approved
for production release** until the live checks below are reviewed. No merge or
Pages deployment was performed during implementation.

- A: occurrence IDs, scoped multi-offer pricing, uncertainty, status and regression tests.
- B: targeted card extraction, optional free TinyFish POST Fetch / GET Search,
  removal of the old retrieval service, and retained browser/discovery recovery.
- C: honest Pages labels, Berlin-time past filtering, frozen audit and CI gates.
- D: bounded daily verification, TTL overlay, shared builds and direct daily
  publication, browser smoke, operating documentation and this review report.

## Reproducible frozen audit

`tests/fixtures/events_scored_2026-10-11.json` is a byte-for-byte copy of the
original committed scored dataset. `data/events_scored.json` and `data/events.json`
were left unchanged during implementation. The frozen input hash and per-source
counts are in `docs/r1-frozen-audit.json`. Reproduce with:

```bash
.venv/bin/python scripts/audit_events.py \
  --input tests/fixtures/events_scored_2026-10-11.json \
  --now 2026-10-17 --output /tmp/r1-audit.json
```

| Stored-data metric | Before (475 rows) | After normalization (464 rows) |
|---|---:|---:|
| Unknown price | 255 | 318 |
| Numeric zero | 96 | 26 |
| Labelled Free | 96 | 25 |
| Explicit free-admission evidence | not modelled | 25 |
| Missing candidate detail link | 148 | 139 |
| Content-verified detail link | not modelled | 0 |
| Blank venue | 298 | 289 |
| Before 2026-10-17 | 353 | 343 |
| Student offer evidence | not modelled | 1 |
| Generic reduced offer evidence | not modelled | 1 |
| Reported sold out | not modelled | 30 |
| Reported cancelled | not modelled | 3 |

Nine badge/category/offer rows are quarantined with their reasons in the audit;
two duplicate rows merge. All other 464 occurrences are retained, including the
valid €18.40–€28.70 Thikwa range whose old title contains a partial price. The
legacy Free-to-paid festival range is now €0–€45 and never simply Free. These
figures describe stored listing evidence, not live ticket inventory. They do not
establish that all 96 old zeros were wrong, or that any old `has_detail_link=true`
URL was independently verified. The more conservative Free proof deliberately
leaves bare “Free” keywords and unsupported zeros unresolved. Expired historical
free evidence is hidden by the verified-free filter in the actual page build.

| Targeted source (frozen normalization) | Retained | Missing candidate links | Blank venues |
|---|---:|---:|---:|
| Berlin Bühnen | 130 | 130 | 47 |
| ufaFabrik | 10 | 9 | 10 |
| Rausgegangen | 123 | 0 | 88 |

No previously content-verified link is downgraded: the original dataset had no
content-verification evidence. Source fixtures preserve both genuine adjacent
events, discover 2/2 candidate URLs and 2/2 venues, and attach three price tiers
only to their own card. These are **synthetic sanitized relationship fixtures**,
not captures of current live layouts. Their verified-link rate is 0% until
fetched/matched. Do not interpret fixture success as achieving the >95% live
link / >90% venue targets. Missing live source captures and ongoing source gaps
remain release limitations; no unknown field was fabricated to hit a target.

## Validation and publication path

- Python 3.11 dependencies installed from unchanged `requirements.txt`.
- 197 Python tests pass, including all existing tests and replacements for the
  retired provider contracts. Two old free-sort inputs now explicitly say
  “Free admission”; their sorting assertions are unchanged.
- Frontend syntax and deterministic Berlin-midnight/unknown-time/ICS checks pass
  with `node tests/test_frontend.cjs`.
- All five workflows pass YAML parsing and actionlint v1.7.7. The official
  actionlint release archive was verified against its published SHA-256 manifest.
- Offline canonical build: 608 raw records → 464 displayed dataset records,
  with the existing preference exclusions/cutoff retained. Independent frozen
  normalization: 475 scored records → 464. JSON/schema/quality gates pass.
- Chromium smoke: 112 upcoming rows by default; 464 including past; zero fresh
  verified-free rows from this historical snapshot; search and downloaded ICS
  pass; desktop/mobile render with zero page errors. HTML, screenshots, ICS and
  smoke report are generated under `/tmp/r1-smoke` by `scripts/smoke_pages.py`.
- Offline verifier at `2026-10-17T07:17:00Z`: 40 targets selected, zero HTTP,
  Fetch or Search calls. Keyless fallback is exercised by mocked blocked HTTP;
  it preserves observations and reports zero provider calls.
- Last successful weekly run inspected on GitHub's public run page:
  https://github.com/JsonLord/event-scraper-github-actions/actions/runs/38173110961
  (2026-10-11 20:39:17 UTC, commit `55f2708`, Success, duration 6m45s,
  aggregate-and-deploy and Publish weekly event table completed). This is a
  historical baseline run, not validation of this branch's deployment.

Daily, weekly and manual workflows call `scripts/build_page_dataset.py`; the
daily workflow commits the compact overlay **and deploys in that same run**.
It does not depend on a token-created push triggering Pages. All share `pages`
concurrency and check out the latest branch after acquiring the workflow lock.
An external push race rejects the push and stops deployment, with no forced
rebase of generated JSON. The Sunday 17:00 UTC matrix, low-aggregate guard,
per-day horizon, recovery stages, stream tables and ICS export remain.

## Usage, permissions and remaining release checks

No TinyFish key is configured in this cloud environment and no live TinyFish
requests were made. The only callable endpoints are POST
`https://api.fetch.tinyfish.ai` and GET `https://api.search.tinyfish.ai`, both
with `X-API-Key`. Tests cover HTML payloads, encoded GET parameters, partial
per-URL errors, malformed JSON, redirects, missing key, 401/403/429, secret-safe
errors and separate usage counters. Worst-case daily usage is 30 fetched URLs
and 12 searches, below the published 1,000 Fetch URLs/day, 150 URLs/min,
30 searches/min and 500 searches/hour. Every failed attempt consumes quota.
Provider calls are spaced by at least a second; total Search calls per run
remain below the per-minute ceiling. Discovery uses at most two Fetch URLs per
source process. Account usage shared with other applications is not enforceable
by this repository and must be monitored by the owner. No paid API or top-up
path exists here.

Required manual checks before release:

1. Review source-card selectors against current Berlin Bühnen/ufaFabrik pages;
   collect small sanitized real-page fixtures and assess missing venue/link rates.
   Current live source access was blocked by this cloud network policy.
2. Recheck the supplied TinyFish reference contracts and current free pricing at
   the official documentation URLs in `spec.md`. Direct requests to those sites
   were blocked by the cloud proxy. No live provider schema/rate-limit test is
   claimed. Optionally configure `TINYFISH_API_KEY` securely in Actions and perform
   one bounded dispatch; never supply the value in chat or source control.
3. After review/merge, manually dispatch the verifier and inspect usage, overlay
   freshness, Pages environment permissions, artifact and final deployment.
   Review the Actions logs and deployed site; no production deployment was
   attempted here. Unit tests and actionlint validate the wiring, not platform
   deployment permissions or current vendor behavior.

Cloud setup instructions and a restricted domain expansion were saved as a
configuration draft. Review/save those environment settings and publish the
cloud environment to activate them; saving the draft did not apply networking
or publish the environment. GitHub API access remains blocked in the current
instance; Git reads and public GitHub web pages work through existing access.

**Security finding:** the superseded historical specification contained a
plaintext credential-like value. The owner must manually **revoke/rotate** it.
No value was printed, used, copied into fixtures or committed. The current spec
is already sanitized. No history rewrite or production secret change was made.

## PR #33 hardening follow-up (2026-10-17; supersedes access notes above)

Official Fetch and Search references were fetched successfully over verified
HTTPS on this review. Fetch documents `ttl: 0` for live content,
`per_url_timeout_ms` (1–110000), a 110-second backend / 120-second CDN ceiling,
and at least a 150-second client timeout. Both endpoints document 402 allowance
exhaustion. Current Search reference lists 12,000 free requests/day and 30/min;
Fetch lists 1,000 URLs/day and 150/min. No wallet action or paid endpoint was used.

The client now sends `ttl: 0` and a 45-second per-URL budget, waits up to 150 seconds
for a Fetch response (8-second connect), and disables both provider operations on
401/402/403/429. Whitelisted diagnostics contain operation, HTTP status, schema
validity, result count, per-URL error codes and duration, without credentials,
queries or URLs. A shared 900-second verifier deadline reserves enough time for
each next request; when less than 159 seconds remains, no new Fetch is attempted.
The 20-minute job deadline leaves the remaining five minutes for setup/build/
commit operations. Maximum quotas are ceilings, not promises to process every
target within that deadline. Normal retrieval and provider budgets stay separate.

Direct public source access also succeeded on this review. Berlin Bühnen uses
`hylo-router-link.event-list-item` wrappers, not ordinary anchors; the real title
is the `h3` in `slot=end`, and the wrapper has the occurrence URL. ufaFabrik uses
`li.calendar-view-day__row`, with the shared date on its enclosing calendar cell
and prices/title/venue confined to each row. The adapters now recognize those
structures. Sanitized **real listing** fixtures (two Berlin Bühnen cards and
seven ufaFabrik rows) replace reliance on synthetic layout evidence. Full-page
inspection found 24 Berlin Bühnen cards and 18 ufaFabrik rows, all with candidate
links and venues. These are current page observations, not retrospective repair
of the frozen dataset or content-verified deep links.

Semantic matching now also reads literal date/time and labelled venue text when
classes, JSON-LD and `datetime` attributes are absent. It rejects multiple
performances and neighboring event headings. Missing venue may be matched only
through official canonical occurrence identity or matching official event ID,
still requiring title and exact performance date/time. Known venue mismatches,
generic venue/listing pages and third-party identity shortcuts remain UNKNOWN.
Explicit scoped “Tickets verfügbar” may support reported availability; a ticket
button, successful HTTP response or search snippet never does.

A manual-only qualification mode was added to the existing Fetch Strategy Probe.
It has read-only repository permissions, hard limits of two Search calls and two
Fetch URLs, no deployment step, and uses only the existing repository secret.
The cloud process has no key; listing Actions secrets is denied to this
integration, so availability is established only by the qualification run itself.
Live provider results and final GO/NO-GO decisions will be recorded after that run.

## Completed qualification and release decision (reviewed 2026-10-18)

The manual-only run [39065395186](https://github.com/JsonLord/event-scraper-github-actions/actions/runs/39065395186)
used the existing `TINYFISH_API_KEY` Actions secret on `ubuntu-latest`, with
read-only repository permissions. The cloud process never received the value.
No production workflow was dispatched, no schedule was activated and no Pages
artifact/deployment was created. The run made **exactly two Fetch URL requests
and two Search calls**. No additional provider calls were made while recovering
or testing the output.

| Operation | HTTP | Response validation | Duration | Content result at qualification time |
|---|---:|---|---:|---|
| Search: Berlin Bühnen title + venue + date | 200 | `results[]`, 10 candidates | 1.393 s | Exact target absent; candidates remain unverified |
| Fetch: Berlin Bühnen selected occurrence | 200 | HTML result + `errors[]` envelope | 2.043 s | Initially unmatched; multi-performance page correctly stayed UNKNOWN |
| Search: ufaFabrik title + venue + date | 200 | `results[]`, 1 candidate | 1.855 s | Exact target found, still only a candidate |
| Fetch: ufaFabrik selected occurrence | 200 | HTML result + `errors[]` envelope | 1.522 s | Title/date/time + official URL matched; price/discount evidence survived |

Both source robots policies permitted the requested event URLs. All provider
calls reported `ok`; no HTTP authentication, quota or rate error was observed.
402 allowance exhaustion and 401/403/429 shutdown are covered by deterministic
mock tests, not induced against the live account. The requests used `ttl: 0`,
`format: html`, `links: true`, and `per_url_timeout_ms: 45000`; the client Fetch
connect/read timeout was 8/150 seconds. No paid Agent/Browser endpoint, wallet
operation, checkout or login flow was invoked. Account-wide allowance/wallet
state was not queried and zero billing cannot be independently certified.

Sanitized captures and the original qualification report are committed under
`tests/fixtures/tinyfish_live/`, with provenance and transformation details in
that directory's README. The Fetch envelopes retain `url`, `final_url`, `format`
and semantic `text`; no original `datetime` attributes survive. Scripts were
removed during sanitization, so the captures do not independently prove that
TinyFish removed all JSON-LD. The parser does not require it.

The Berlin Bühnen output contained the selected 18 October 11:00 occurrence,
a cancelled **25 October** occurrence, and unrelated recommendations. The parser
now scopes its selected hero and individual performance rows, with venue and
price from the same detail's labelled accordions. The current offline replay
matches the selected title/date/time/venue and €12–€14 range, without importing
the other date's cancellation or claiming tickets are available. Mutating the
selected row to cancelled is detected; choosing another performance at this URL
is rejected. ufaFabrik replay now reads the venue from its captured article
header and retains regular €26 / reduced €22 / student €12 with advance-sale
conditions. Its “Karten kaufen” link remains availability UNKNOWN. Both real
captured detail pages now match in offline replay (2/2); **no second live Fetch
qualification of these parser changes was performed**.

The original report deliberately preserves the initial live result: 1 matched,
1 unmatched. Later parser fixes were validated offline against those exact
sanitized responses. Successful HTTP status was never treated as verified event
content. The source listing repairs also retain all 24 Berlin Bühnen and 18
ufaFabrik rows observed during this review, each with an extracted venue and
candidate event URL. These small current samples do not repair the frozen
October 11 records or establish general coverage targets.

Artifact retrieval from this cloud machine's signed-storage route failed.
Read-only evidence recovery jobs [39065574438](https://github.com/JsonLord/event-scraper-github-actions/actions/runs/39065574438)
and [39074656872](https://github.com/JsonLord/event-scraper-github-actions/actions/runs/39074656872)
read the same saved artifact and exposed sanitized evidence through GitHub check
annotations. The larger response was recovered in nine complete Base64 chunks
before JSON parsing; a truncated annotation was never accepted as a fixture.
Those jobs did not bind or invoke a provider transport, and did not deploy.

| Area | GO / NO-GO | Exact scope and remaining gate |
|---|---|---|
| Offline data correctness | **GO** | 212 Python tests, frontend checks, workflow actionlint, frozen audit/schema gate and Chromium smoke pass locally; includes both real semantic captures and cross-performance cancellation regressions. |
| Live TinyFish compatibility | **GO, limited qualification** | Existing key accepted; both documented endpoints returned valid data in all four requests. No claim about long-run quotas, every error response or billing state. |
| Live source extraction | **NO-GO for broad production coverage** | Real listing samples and 2/2 captured-detail replays pass; the initial live parser matched 1/2. Broader layout/occurrence coverage and live requalification of the final parser remain untested. |
| Daily verification | **NO-GO for production activation** | Budgets, deadlines, matching, expiry and fail-closed behavior are tested offline. The daily end-to-end runtime/persistence path was not dispatched because it also deploys; it still needs an approved non-publishing integration run. |
| GitHub Pages production deployment | **NO-GO / approval withheld** | Offline build, responsive rendering and ICS pass. No production deployment or merge was requested or performed. |

The frozen input datasets and production verification overlay were left
unchanged. The audit baseline still normalizes 475 → 464 records, quarantining
nine pseudo-titles and merging two duplicates. Changes are on PR #33's existing
branch only. The historical credential revoke/rotate finding remains open.

## R1.2 end-to-end staging qualification (2026-10-18)

The current handoff is [R12_QUALIFICATION_REPORT.md](R12_QUALIFICATION_REPORT.md),
with three committed machine-readable run summaries, bounded direct diagnostics,
and [release/activation controls](R12_RELEASE_CONTROLS.md). This supersedes the
R1.1 statement that the daily pipeline had not been exercised end to end.

The production discovery/verifier/overlay/materialization pipeline ran in a
manual-only `contents: read` workflow with all generated data under runner temporary
storage. Across the bounded qualification, 56 rows/candidates were observed,
seven selected, and six matched (85.7%). Three student-offer observations and one
selected cancellation were confirmed; ticket inventory remained UNKNOWN. The
second simulated run preserved fresh state with no network calls. Expiry,
production-data immutability, shared build, search, responsive rendering and ICS
passed for the six-event cohort. Rausgegangen remained unverified and its empty
completion builds did not claim a passing browser smoke.

Combined usage was six Fetch URLs, two Search calls and 21 direct HTTP attempts
including diagnosis, at most eight per host. All provider responses were HTTP
200 with valid envelopes; useful source evidence was assessed separately.
No additional Fetch calls were made after the qualification ceiling was reached.
Original production JSON and overlay files are unchanged.

Source coverage remains **NO-GO** for broad release. Daily integration and
uncertainty handling are **GO within the exercised staging scope**. Fail-closed
activation controls are **GO**, but neither feature is enabled or approved for
activation. Pages production deployment is **NO-GO** pending source coverage and
explicit review. Merging can no longer auto-publish through the push-triggered
Pages workflow; its jobs require manual dispatch and a repository flag. Legacy
weekly data persistence still exists and must be paused by the owner if a future
merge requires a full production data-write freeze. No merge, deployment,
production workflow dispatch or repository-variable change was performed.

## R1.3 follow-up — 18 October 2026

[R1.3 qualification](R13_QUALIFICATION_REPORT.md) supersedes the earlier zero-Raus
source-presence result: two independent Raus detail occurrences now match through
the shared production matcher. Listing discovery and Raus occurrence-bound price
coverage remain incomplete. Coverage metrics no longer accept candidates as proof.
The Python suite now has 226 passing tests. Three read-only staging runs preserved
production files and passed state, TTL, shared build, Chromium, search and ICS
checks. The release recommendation is conditional technical GO for a separately
approved fresh Berlin Bühnen + ufaFabrik release, NO-GO for the full three-source
release, and NO-GO for daily activation now. Draft status and release gates remain.

## R1.4 pilot release candidate — 18 October 2026

[R1.4 release evidence](R14_RELEASE_CANDIDATE.md) now qualifies an isolated,
manifest-gated two-source pilot: five published exact matches from 55 discovered
occurrences, on two dates per source. Technical GO is not authorization to merge,
publish or schedule. The new guards require a reviewed, fresh main-commit artifact;
legacy weekly writes and daily/weekly publishing require a separate unrestricted
profile/flag and cannot overwrite a pilot. Claim expiry is enforced in the
preview as well as at promotion. All 252 Python tests pass; production datasets,
activation settings and draft status remain unchanged.
