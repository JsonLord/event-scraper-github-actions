# Berlin Event Scraper — Round 1 Quality & TinyFish Free-Tier Verification

**Status:** Implementation specification · **Version:** R1.1 (TinyFish amendment) · **Date:** 2026-10-17  
**Repository:** https://github.com/JsonLord/event-scraper-github-actions  
**Published site:** https://jsonlord.github.io/event-scraper-github-actions/  
**Canonical plan:** This document replaces the repository's superseded historical `spec.md` for future development. Retain a sanitized history in Git as appropriate; never copy credentials into this file.

## 0. Decision summary

Implement a **GitHub-native, zero-required-spend** first round: preserve the existing weekly scraper and GitHub Pages, improve event identity, prices, source links, and available status signals, and introduce a bounded **daily verification** workflow on GitHub Actions. Integrate **TinyFish free Search and Fetch** as optional hosted retrieval tools, replacing Jina Reader. **No LLM, paid Agent/Browser API, paid proxy, CAPTCHA-solving service, or self-hosted server is required.** Direct HTTP remains the keyless default; TinyFish improves rendered-page and deep-link coverage only when `TINYFISH_API_KEY` is configured. Browser-control automation and paid providers are out of R1's critical path.

Definition of success: trustworthy *uncertainty* is better than confident falsehood. Never state `Free`, `Available`, `Student discount`, or `Valid event link` without supporting evidence.

## 1. Audited baseline (2026-10-17)

On repository `main`, `data/events_scored.json` has `generated_at=2026-10-11`, 475 events for 2026-10-11 through 2026-10-18. These figures are counts from stored data, not independently confirmed live ticket-shop facts:

| Metric | Baseline |
|---|---:|
| Unknown prices (`price: null`) | 255 / 475 (53.7%) |
| `price: 0` labelled `Free`, sometimes without valid evidence | 96 / 475 |
| No event-specific link (`has_detail_link: false`) | 148 / 475 (31.2%) |
| Missing venue | 298 / 475 (62.7%) |
| Events before 2026-10-17 | 353 / 475 |
| Event-status fields (`availability`, `ticket_status`, etc.) | 0 |
| Rows containing `sold out` / `Ausverkauft` language | 34; not all separately verified |
| Rows containing cancellation language | 3; not all separately verified |

Dominant errors:
- `Ausverkauft Theater`, `Theater Comedy & Kabarett`, `Ermäßigt €17,00`, `Studenten (nur im VVK) €12,00` appear as *titles*.
- `0–45€` is collapsed to `Free` with no warning of paid tiers; `keine Preisangabe` can still produce `Free`.
- `berlin-buehnen.de`: 132/132 rows lack detail URLs and prices; `ufafabrik.de`: 16/17 lack detail URLs.
- Three exact/folded duplicate groups exist, with additional likely semantic duplicates.
- Frontend currently filters search/free but not elapsed dates.

Current files of interest: `scripts/event_utils.py`, `scripts/generic_event_scraper.py`, `scripts/score_events.py`, `scripts/recover_failed.py`, `web/index.html`, `.github/workflows/weekly-event-scraper.yml`, `.github/workflows/jekyll-gh-pages.yml`, `tests/`.

## 2. Execution and cost requirements

### 2.1 Free-first platform matrix

| Tier | Service | R1 mode | Hard constraint |
|---|---|---|---|
| 0 | GitHub Actions, `ubuntu-latest` **standard runner** | Required | Public repo standard Actions usage is free; no larger or paid runners |
| 0 | GitHub Pages | Required | Static files only; no hosted backend |
| 0 | Python `requests`, `beautifulsoup4`, `lxml`, existing deterministic extractors | Required | Default verification strategy |
| 1 | TinyFish **Fetch** (POST `https://api.fetch.tinyfish.ai`) | Optional GitHub Actions fallback | Free within published limits: 150 URLs/min, 1,000 URLs/day; render JS-heavy public pages; key from `TINYFISH_API_KEY` |
| 1 | TinyFish **Search** (GET `https://api.search.tinyfish.ai`) | Optional detail-link recovery | Free within published limits: 30 requests/min, 500 requests/hour; results are **candidates**, not verified event links |
| 2 | Cloudflare Browser Run / TinyFish **Agent**, **Browser**, **Monitor** / paid proxies | **Deferred** | Do not invoke, buy, fund, or silently upgrade to metered APIs in R1 |
| 2 | Playwright / Browserless / additional CloakBrowser sessions | **Deferred** from daily verification | Preserve existing discovery behavior other than replacing Jina; do not add new browser sessions in R1 |

Verified vendor sources (2026-10-17): https://www.tinyfish.ai/pricing ; https://docs.tinyfish.ai/fetch-api/index ; https://docs.tinyfish.ai/search-api/index ; https://docs.tinyfish.ai/fetch-api/reference ; https://docs.tinyfish.ai/search-api/reference . TinyFish Search/Fetch remain free at a $0 wallet balance; published limits and provider terms may change. No guarantee of unrestricted access or accurate ticket inventory.

### 2.2 Hard budgets

- Daily verifier examines at most `max_events_per_run=40` distinct event targets. Bound **direct HTTP** attempts to `max_http_requests_per_run=40` and `max_requests_per_host=8`, each **including redirects and retries**; `max_concurrent_requests=2`; `max_response_bytes=1_500_000` per URL; `max_total_response_bytes=25_000_000`; 8-s connect and 12-s read timeout; at most one retry on transient failure; back off on `429`, do not repeatedly challenge `403`/`429`. Separately bound TinyFish to `max_tinyfish_fetch_urls_per_run=30` and `max_tinyfish_search_queries_per_run=12`, both counted **including failures/retries**; a retrieved URL still consumes one of 40 target slots. Use ≤10 URLs per Fetch POST (prefer batches of ≤5), and a conservative global throughput ceiling of 1 TinyFish request/second. No repeated full-source search loops.
- Prioritize event dates coming in the next 48 h, then source coverage and score, then the next 7 days; exclude past events. Deterministic fairness across sources; do not starve one host.
- The direct-HTTP/TinyFish verifier does **not** follow ticket purchase flows, submit forms, authenticate, attempt CAPTCHA/Cloudflare bypass or reserve tickets.
- `TINYFISH_API_KEY` is an optional **free Search/Fetch** credential, not authorization to spend. No auto-top-up, Wallet action, paid Agent/Browser/Monitor endpoint, or hidden usage. Add `TINYFISH_ENABLED=true` (effective only when key present), `TINYFISH_FETCH_ENABLED=true`, `TINYFISH_SEARCH_ENABLED=true`; record usage and fail closed on 401/403/429/quota exhaustion. Disable TinyFish calls in tests and offline dry runs. Keep below account-level daily limits even if other applications share the key; do not interpret provider HTTP 200 as every URL succeeding.
- All secrets from GitHub Actions `secrets`, never repo JSON, logs, generated HTML, screenshots or PR output.
- Store compact JSON evidence only; redact session identifiers, ticket tokens, tracking cookies and other sensitive tokens. Do not commit raw HTML captures of ticket pages.

### 2.3 TinyFish integration contract (replaces Jina Reader)

**Where the key lives**

- Local development: load `TINYFISH_API_KEY` from the process environment, optionally via a gitignored `.env` file. Add `TINYFISH_API_KEY=` to `.env.example` with an empty placeholder; **never** commit a real value.
- GitHub repository: create Actions secret **`TINYFISH_API_KEY`** under **Settings → Secrets and variables → Actions → Repository secrets**. Expose only to the scrape and daily verification steps via `env: TINYFISH_API_KEY: ${{ secrets.TINYFISH_API_KEY }}`. The GitHub Pages frontend must never see it.
- Secrets unavailable (including untrusted fork PRs) ⇒ direct HTTP only, with explicit `tinyfish_skipped_no_key` diagnostics; publish and tests still work. Avoid outbound calls entirely in offline tests.

**Exact REST requests (verified from TinyFish documentation)**

```bash
# Search: discover candidate event-detail URLs for unresolved items. No secrets in URL.
curl -G 'https://api.search.tinyfish.ai' \
  --data-urlencode 'query=site:example.org "Example Event" Berlin 17.10.2026' \
  --data-urlencode 'location=DE' \
  --data-urlencode 'language=de' \
  -H "X-API-Key: $TINYFISH_API_KEY"

# Fetch: obtain rendered content of a known event URL (up to 10 URLs per POST).
curl -X POST 'https://api.fetch.tinyfish.ai' \
  -H "X-API-Key: $TINYFISH_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"urls":["https://example.org/events/example-event"],"format":"html","links":true}'
```

**Response handling:** Search returns `results[]` containing titles/snippets/URLs and metadata. Fetch returns `results[]` with `url`, `final_url`, `title`, `format`, `text`, and possibly links, plus **per-URL `errors[]`** even when the overall POST returns 200. Reconcile by requested URL/final URL rather than array index or assuming all succeed. The Fetch default format is `markdown`; request **`format: "html"`** explicitly so existing BeautifulSoup/HTML extraction can be reused. TinyFish's `html` output is semantic/processed HTML, **not guaranteed to preserve all original JSON-LD/scripts or event-card DOM structure**. Test coverage and use deterministic text extraction and link-evidence handling when structured markup is absent; do not infer missing fields. The `links` option can provide candidate event URLs but does not prove they are genuine event pages.

**Routing, to minimize requests and false positives:**

1. Try the established direct GET and structured JSON-LD/DOM extractors first, on existing programme URL or event URL.
2. For blocked, JS-empty or low-quality detail pages, call **TinyFish Fetch** on the *known* URL; accept only target-matching content and distinguish missing evidence from negative evidence. Never use a single page's arbitrary prices/statuses for another event.
3. If an event's link is missing, broken, generic, or homepage-only, use **TinyFish Search** with distinctive event title + venue + date + Berlin, optionally `site:<official-host>`, `location=DE`, `language=de`. Verify candidate destination title, performance date, and venue **by fetching the candidate** (direct first, TinyFish Fetch if needed). A search result alone is **never** `detail_link_status=verified`.
4. For extraction that is difficult from processed HTML, compare 2–3 sanitized source fixtures against direct HTML, TinyFish HTML, and (only if necessary) TinyFish Markdown, without quietly adding another paid service.
5. On missing key, 401/403, rate limit, per-URL error, challenge, low-confidence result, or mismatch, keep unknown/unverified status and existing valid data. Do not erase stronger evidence, silently guess `Free`, or assert tickets are available.

**Cost and privacy:** Published limits are Search 30 requests/min and 500 requests/hour, and Fetch 150 URLs/min and 1,000 URLs/day, free with $0 Wallet. Use the much lower per-workflow caps above. Only send public event URLs and minimal public query text; never pass visitor IDs, ticket cookies, login state, purchased tickets, personal data, secret-bearing URLs, or private endpoints. Redact URL tokens before logging. Reject non-HTTP(S), private hosts and localhost before any network fetch. Follow source/robots restrictions. The free Fetch API's JS rendering is content retrieval, **not** a live inventory guarantee or a multi-step login/checkout browser.

**Change existing discovery fallback:** Replace the Jina Reader integration in `scripts/generic_event_scraper.py` and workflow secrets with TinyFish Fetch, while preserving existing direct HTTP and any existing optional CloakBrowser final fallback without adding new browser work. Remove Jina-key dependence and update/rewrite Jina-specific tests to TinyFish contract tests. No automatic upgrade to TinyFish Agent, Browser, or Monitor.

## 3. Scope and requirements (one PR, isolated commits)

### R1-A — Safe data normalization (P0; required)

**A1. Event title/classification**
- Upgrade title validation so badge, category, venue-only and price-only text cannot be emitted as event titles (examples listed above). Add negative fixtures and valid-counterexamples (genuine shows named `Theater`, `Free`, etc.; avoid unbounded blacklists).
- Keep German umlauts, ß, punctuation, stylized proper names and word order. Never use title-casing to repair a real German title.
- Prefer a true event heading or structured `Event.name`; then a heading-link text; then event URL slug *only if associated with the current card*. Do not confuse adjacent cards or a generic programme heading with an event.
- When no reliable title can be found, **reject/quarantine** the row with reason; never manufacture names.
- Ensure date/time and any title recovered from a card come from the same event card/element; no cross-event leakage.

**A2. Price correctness**
- Preserve the legacy `price` field for compatibility, but add **structured offers** and evidence. `None` means unknown, *never* free.
- A price range `0–45€` is `price_min=0`, `price_max=45`, `price_type=range`, `price_label="From €0 · paid tiers"`; **not** `Free` without explicit free-admission evidence. Single nonzero ticket `€17` remains a single price. `keine Preisangabe` means unknown absent stronger evidence, regardless of other unrelated numeric zeroes.
- Do not attach ticket prices shown elsewhere on the page to an unrelated event. Orphaned `Ermäßigt €17,00` / `Studenten ... €12` rows must be excluded from event list; attach an offer only when event-card/structured-data association is proven.
- `ermäßigt` / `reduced` is generic concession; **not** automatically a student ticket. `Studenten/Studierende/Student` with matching price **and same-card relationship** may be recorded as student eligible; preserve conditions `nur im VVK`, ID requirements if visible; otherwise `student_discount=unknown`.
- Multiple JSON-LD `offers` must be processed safely (arrays, nested offers/availability, `lowPrice`, `highPrice`, currency and offer URLs when meaningful). Ignore data from unrelated Event/Offer nodes.
- Keep `price` as lowest *verified applicable* admission price or `null` if unknown/conflicting. Maintain €20 recommendation filter for known eligible options, but label reduced-only eligibility and do not silently treat unknown as ≤€20 verified. `Free only` uses an explicit `free_admission_confirmed` flag, not merely `price === 0`.
- Price conflicts are marked `conflicted` with evidence; they must not be silently resolved in favor of free/cheap.

**A3. Availability and event status**
- Distinguish event cancellation from ticket inventory. Proposed `event_status = scheduled|cancelled|postponed|unknown`; `ticket_status = sold_out|available|unknown|not_applicable`.
- Detect `Ausverkauft`, `Sold out`, `Abgesagt`, `Cancelled`, `Postponed` from the *event-specific* card/detail or structured Event/Offer metadata. Stopwords from generic navigation do not count.
- Source text alone can support `reported_sold_out` / `reported_cancelled` UI with date of observation, but `available` requires explicit positive availability evidence for the relevant **date/performance** (e.g. `InStock` offer); the presence of `Tickets` button/link is not positive evidence.
- Do not present stale reports as live inventory. Display `Last checked [timestamp]`, with `Availability unknown` on expired/unreachable data. Cancellation can be displayed even when price is unknown.
- A `403`, challenge page, timeout or absent inventory means **unknown**, never `available` or `sold_out` by inference.

**A4. Identity, deduplication, links and venue**
- Add a stable `event_id` based on canonical event URL **plus occurrence date/time** where possible, otherwise normalized title + date/time + venue + source. Do not collapse two performances of the same production into one event.
- Normalize German accents for **matching only**, not displayed names. Deduplicate across sources using strong exact evidence first (canonical event URL; normalized title+occurrence+venue), then conservative fuzzy candidates with a high threshold. Preserve a canonical primary event plus alternate source URLs / evidence; do not silently discard richer price or links.
- Replace misleading boolean semantics with `detail_link_status = missing|candidate|verified|invalid`. `url != source_url` alone means **candidate**, not verified. Verify only a bounded subset by fetching the target and matching title/date or strong page metadata, not merely `HTTP 200`.
- If no verified deep link: show a clearly labelled `Source listing` link; do not claim that link opens the event. Do not falsely promote a URL to `verified` because its host differs from the listing.
- Improve missing venue extraction for `berlin-buehnen.de`, `rausgegangen.de`, and `ufafabrik.de` where same-card or structured venue evidence exists. Leave blank otherwise.

### R1-B — Targeted source repair (P0/P1; required)

- **Berlin Bühnen:** dedicated adapter or card-level extractor for actual event title, valid event/event-booking href, date+time, venue and status. Target the 132 historically low-quality rows. Support its per-day `?date=` horizon without multiplying requests unnecessarily. Handle link anchors that are unrelated navigation. Add sanitized HTML fixtures.
- **ufaFabrik:** bind admission/reduced/student price text to the correct event card; never create price-only event rows; follow genuine event-detail links when present. Add fixtures.
- **Rausgegangen:** enforce exact range/free/unknown semantics; recover venue where the card reliably supplies it. No broad re-scrape required.
- Allow other sources to continue using the generic scraper. Avoid regressions to the working Meetup and theatre sources.

### R1-C — Low-cost daily verification (P1; required after R1-A/B pass)

Create `scripts/verify_event_details.py` (or equivalent) and `config/verification_policy.json` (or YAML), plus `.github/workflows/daily-event-verification.yml`:

1. Scheduled **once daily**, e.g. `17 7 * * *` UTC, and `workflow_dispatch`; standard `ubuntu-latest`, no self-hosted runner; `timeout-minutes: 20`, permissions scoped to contents write / Pages deployment only where needed, and `concurrency` preventing overlapping commits/deploys.
2. Read the latest persisted `data/events.json` or `data/events_scored.json`; deterministically select upcoming events with candidate detail URLs, subject to 40 total event targets, a separately bounded direct-HTTP attempt budget (including redirects/retries), and independent capped TinyFish Fetch/Search budgets; skip stale/past rows and already-fresh detail checks unless priorities changed.
3. Fetch public event-detail HTML with `requests.Session` first; enforce budget/timeouts, robots/site-policy restrictions, response MIME/size checks, challenge detection, and normalized URLs. On blocked/incomplete/JS-only pages, optionally try TinyFish Fetch (`POST`, HTML format), then parse event-bound evidence. For missing generic event links, use TinyFish Search (`GET`) for **candidate discovery only**, confirming destination content before marking verified. Extract JSON-LD and strongly bound DOM/text signals, not generic whole-page keywords.
4. Emit a compact `data/event_verifications.json` **overlay** keyed by stable event_id. Keep last-known verified observations and timestamps, with independent TTLs. A failed check must not erase a valid historical observation, but an expired observation cannot be displayed as current. Avoid writing if the materialized overlay is unchanged.
5. Overlay keys are merged with event data by a **single shared build function**, used by both weekly publish and daily publish; do not fork scoring logic or mutate raw event facts. Explicit precedence and freshness rules; never overwrite newer higher-confidence verified evidence with stale listing text.
6. Daily workflow **publishes updated Pages itself** after generating the merged static JSON, or explicitly invokes a reusable publishing workflow. **Do not assume a push made with the default `GITHUB_TOKEN` will trigger a separate `on: push` workflow**. Weekly scrape/publish must continue working untouched in the absence of the overlay.
7. Handle races between weekly and daily jobs via a repository-wide deploy concurrency group and fresh-checkout/rebase behavior. Never deploy older weekly data on top of newer verified facts. Avoid committing a full regenerated 400-event JSON blob for every status refresh if a small overlay is sufficient.
8. Include an optional `--dry-run`, `--max-events`, `--now` and offline fixture mode to test without network access. Non-fatal unreachable sources become `unknown`, not a pipeline failure; malformed output or unexpectedly empty aggregate should fail rather than replace good data.
9. Remove the Jina Reader fallback and related secret references from the discovery workflow; replace with TinyFish Fetch under explicit free-tier gates. Add TinyFish Search only for event-specific deep-link recovery and verification. Retain the existing optional CloakBrowser discovery behavior without adding any new browser automation in R1. All TinyFish failures must degrade to normal direct HTTP behavior.

### R1-D — User-facing Pages improvements (P0; required)

- Filter past events automatically using local calendar dates for the event's Europe/Berlin timezone, not string comparison to UTC; leave current-day events until their start time is past (if time unknown, retain through day). Provide `Show past events` toggle only if desired; default is off.
- Add displayed **Price**, **Discounts**, **Tickets**, and **Checked** information without breaking category streams, sorting, search or ICS export. Prefer a compact UI and responsive layout; preserve an obvious link to source evidence.
- Labels must differentiate `Free admission`, `From €0 · paid tiers`, `€20 · Student €12`, `Reduced €12 (eligibility unverified)`, `Price unknown`, `Reported sold out`, `Cancelled`, `Availability unknown`, `Last checked ...`.
- Show `Student discount verified` only when student-specific eligibility text is evidenced. No student discount from generic `Ermäßigt`.
- `Free only` uses verified explicit free admission; add a filter for `Student discount known` only when the field is populated; optional `Hide sold out` and `Hide cancelled` defaults recommended.
- Avoid false freshness: display **source observation timestamp** and verification timestamp distinctly, not `generated_at` as proof the tickets were checked.
- Keep `event_id` stable for selection/ICS behavior; support existing scored JSON fields as fallback.
- Put quality/source-specific coverage diagnostics in workflow summary or `data/quality_report.json`; surface dataset freshness warning when scan is old.

### R1-E — Quality gates and documentation (P0; required)

- Add fixture-based tests reproducing all observed errors; preserve existing tests. Cover malformed date/time, category-only headings, orphan price rows, student pricing eligibility, `€0–€45`, `keine Preisangabe`, genuine free events, multiple structured offers, sold out/cancelled, corrupted HTML, challenge pages, no detail URL, redirect to homepage, duplicate occurrences, stale overlays and timezone/DST behavior.
- Build a deterministic `scripts/audit_events.py --input ... --output ...` with counts for: published, skipped, unknown price, **explicit** free, conflicts, bogus-title candidates, missing/candidate/verified links, missing venues, known/reported sold out, cancellations, student evidence, and stale checks; also **per-source** rates.
- Pre-publish gate: reject unsafe schema/invalid generated JSON; fail on meaningful regressions relative to checked-in fixtures/baselines (not unstable exact counts per live source). Preserve the existing aggregate-collapse guard.
- Public CI: `pytest` + lightweight CLI smoke tests and static frontend smoke/JS tests if runtime available. All fixture tests must pass offline without API keys.
- Document price/status evidence hierarchy, quota settings, workflow dispatch, limits, manual check steps, expected failures, and explicit non-guarantees.
- Security: current superseded `spec.md` contains a plaintext API-key-like value. **Never repeat the value.** Replace documentation with this sanitized spec and add an explicit user-facing security finding to the PR report: owner must **revoke/rotate** the historical credential. Code edits do not remove Git history; do not rewrite history or rotate secrets without approval.

## 4. Proposed backward-compatible schema (illustrative)

Keep all existing keys (`title`, `date`, `time`, `price`, `description`, `url`, `source_url`, `venue`, `has_detail_link`, `stream`, `score`...). Add:

```json
{
  "event_id": "sha256:<stable occurrence hash>",
  "event_status": "scheduled",
  "ticket_status": "unknown",
  "detail_link_status": "candidate",
  "price": null,
  "price_status": "unknown",
  "price_min": null,
  "price_max": null,
  "free_admission_confirmed": false,
  "offers": [
    {
      "kind": "student",
      "amount_eur": 12.0,
      "eligibility": "students; advance-sale only",
      "availability": "unknown",
      "evidence_url": "https://example.org/actual-event",
      "observed_at": "2026-10-17T07:17:00Z"
    }
  ],
  "student_discount_status": "explicit",
  "evidence": {
    "title": {"source": "event_page", "url": "https://example.org/actual-event"},
    "price": {"source": "offer_markup", "url": "https://example.org/actual-event"},
    "status": {"source": "listing_text", "url": "https://example.org/events"}
  },
  "last_verified_at": null
}
```

The example is **fictional, not scraped data**. Exact schema naming may be improved, but retain clear enums, evidence provenance, occurrence identity and backward compatibility. Do not conflate ticket inventory with event cancellation. Reject impossible combinations (e.g. cancelled + confidently available on the same performance).

**Information hierarchy:** event-specific official page + date-bound ticket offer > event-specific machine-readable Event/Offer > correctly associated listing card > third-party description > unsupported keyword. Preserve conflicts, do not invent facts.

**Refresh TTL suggested defaults:** available status 12 h, sold out 24 h, price 48 h, discount 7 d, event cancellation 24 h unless a new authoritative signal exists. Expiry means `unverified/stale`, not automatically invalid; display timestamp for each type.

## 5. Files Codex should inspect/change

### Existing
- `scripts/event_utils.py`: normalization, prices, title/venue, event ID, validation, dedupe.
- `scripts/generic_event_scraper.py`: candidate collection, JSON-LD multi-offers, source adapters, safe detail URL extraction; replace Jina fetch tier with TinyFish Fetch.
- `scripts/score_events.py`: field-aware score/filters, label generation.
- `scripts/recover_failed.py`: event-detail discovery logic if reusable; optional TinyFish Search candidates.
- `web/index.html`: date/status/price/discount display, evidence links, filter controls.
- `.github/workflows/weekly-event-scraper.yml`: retain Sunday 17:00 UTC scrape; inject `TINYFISH_API_KEY` secret only to network steps, remove Jina secret, add quality gate and merge helper, avoid unnecessary extra matrix calls.
- `.github/workflows/jekyll-gh-pages.yml`: build from canonical source and overlay; deploy consistently after code changes.
- `tests/`: extend, do not rewrite existing tests for convenience.

### New (suggested, adapt names to architecture)
- `config/verification_policy.json` (HTTP + TinyFish caps)
- `scripts/tinyfish_client.py` (REST Search/Fetch transport with bounded budgets, no paid endpoints)
- `.env.example` (add a blank `TINYFISH_API_KEY` placeholder, keep `.env` gitignored)
- `scripts/verify_event_details.py`
- `scripts/build_page_dataset.py`
- `scripts/audit_events.py`
- `scripts/source_adapters/berlin_buehnen.py` and `ufafabrik.py` if appropriate
- `.github/workflows/daily-event-verification.yml`
- `tests/fixtures/` sanitized minimal representative HTML
- `tests/test_ticket_evidence.py`, `tests/test_daily_verification.py`, `tests/test_source_adapters.py`, `tests/test_tinyfish_client.py`
- `data/event_verifications.json` (small persisted overlay; initialize empty)

## 6. Acceptance / hard NO-GO conditions

### Unit/integration acceptance
1. No pseudo-title from the known 2026-10-11 fixtures; real neighboring events must remain.
2. `0–45€` **never displays simply `Free`**, and `keine Preisangabe` **never creates a new zero price** without explicit contrary evidence.
3. `Studenten (nur im VVK) €12,00` is an **offer** attached only with sufficient card evidence, **never an event**; `Ermäßigt €12` is not automatically marked a student offer.
4. Known event-specific sold out/cancelled language is represented, with provenance; `Tickets` link alone is **not** an `available` claim.
5. `detail_link_status=verified` requires content confirmation; homepage redirects and generic programme URLs fail verification.
6. Two performances on separate days cannot collapse into one. German spelling and punctuation remain intact.
7. Past events disappear from default view and same-day handling observes Europe/Berlin.
8. Offline fixture suite and all existing tests pass. CI and scheduled workflows stay valid YAML.
9. Daily verifier checks **≤40 event targets**, enforces **≤40 direct HTTP attempts incl. redirects/retries**, **≤30 TinyFish Fetch URLs**, **≤12 TinyFish Search queries** per run, and respects per-host/byte/time/provider limits; independently test all counters incl. partial failures. No TinyFish paid Agent/Browser/Monitor call.
10. TinyFish POST Fetch + GET Search mocks validate `X-API-Key`, required query/body, semantic HTML, `results[]`/`errors[]` partial success, 401/403/429 handling, malformed JSON, missing key, 10-URL batch max, and candidate link verification.
11. Workflow publishes from verification results without relying on a push made by `GITHUB_TOKEN` to retrigger itself; remains usable when zero external secrets are configured.

### Release gate
- Codex must produce a **before/after audit** on the same frozen October 11 dataset and representative source fixtures; report preserved valid rows, corrected rows, quarantined rows, and unresolved sources.
- Compute achieved rates for the source adapters, but **do not silently loosen validation** to inflate counts. Targets for future iterations: >95% true detail links and >90% venue completeness *among applicable, addressable rows* in the two targeted adapters; report shortfalls rather than fabricate values.
- No deploy to `main` without reviewed PR; no force push, token exposure, uncontrolled history rewrite, or mandatory external spend.
- GitHub Pages and ICS still work on a local build. Clearly identify anything blocked by live networking or missing secrets.

## 7. Implementation sequence and commit plan

1. **Commit A — Data model + regression tests + deterministic price/status parsing.** Run tests and frozen-data audit. P0.
2. **Commit B — Targeted Berlin Bühnen and ufaFabrik adapters, link identity and dedupe fixes.** Run fixture tests; compare events preserved vs dropped. P0.
3. **Commit C — Frontend truthful labels, date filter, discount/status display, quality report.** Local static smoke. P0.
4. **Commit D — Bounded daily direct HTTP + optional TinyFish Search/Fetch verification, compact overlay, shared build, daily workflow and deployment wiring.** Dry-run/fixture tests first. P1.
5. **Commit E — Documentation, full test suite, budget compliance, before/after report, PR.** No production release unless gates pass.

If time or access is constrained, submit working commits A–C with D explicitly deferred **rather than** shipping an untested daily publishing workflow. Record the precise blocker and tests.

## 8. Explicitly out of scope

- Paid proxies, residential proxy subscriptions, TinyFish paid Agent/Browser/Monitor, CAPTCHA-solving services, deliberate Cloudflare challenge circumvention, login/session cookies, form submission, shopping-cart or checkout automation.
- Migrating jobs to Debian/DGX, adding a database server, LLM reasoning on every event, automatic event booking.
- Claiming “live ticket availability” from source snippets, stale screenshots, or HTTP 200.
- Adding broad new event sources; first fix existing high-error sources.
- A large framework rewrite or changing core weekly discovery cadence.

## 9. Verification and documentation references

- Source project README: https://github.com/JsonLord/event-scraper-github-actions/blob/main/README.md
- GitHub Actions billing: https://docs.github.com/en/actions/concepts/billing-and-usage
- TinyFish official pricing and free rate limits: https://www.tinyfish.ai/pricing
- TinyFish Fetch contract: https://docs.tinyfish.ai/fetch-api/reference
- TinyFish Search contract: https://docs.tinyfish.ai/search-api/reference
- GitHub Actions GITHUB_TOKEN workflow-trigger limitations: https://docs.github.com/en/actions/how-tos/writing-workflows/choosing-when-your-workflow-runs/triggering-a-workflow

**Operational promise for R1:** GitHub-only deployment with **no mandatory TinyFish account/key**; an optional TinyFish account/key (no card required for Search/Fetch) enriches public pages within conservative free limits. No mandatory spending; best-effort nonintrusive verification and **accurate, honest uncertainty** instead of fictional data.
