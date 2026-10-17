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
