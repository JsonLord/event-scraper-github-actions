# R1.3 release qualification — 18 October 2026

PR #33 remains a draft. No merge, production JSON/overlay write, repository-variable
change, production dispatch or Pages deployment was performed. This report qualifies
bounded source evidence, not the completeness of a city-wide event catalogue.

## Evidence and reproducibility

Starting evidence: [R1.2 report](R12_QUALIFICATION_REPORT.md), especially phases 2/3.
R1.3 reused `fetch-strategy-probe.yml`: manual dispatch only, `contents: read`,
no environment, deployment or downstream dispatch, runner-temporary outputs,
20-minute job limit. Production verifier, overlay and shared builder were reused.

| Phase | Actions run | Commit | Purpose | Discovered / selected / matched / materialized |
|---|---|---|---|---|
| 1 | [39080734421](https://github.com/JsonLord/event-scraper-github-actions/actions/runs/39080734421) | 65e3ac1 | diagnose three destination pages | 31 / 2 / 2 / 2 |
| 2 | [39093373780](https://github.com/JsonLord/event-scraper-github-actions/actions/runs/39093373780) | 5c48f37 | qualify isolated Raus header parser | 32 / 3 / 3 / 3 |
| 3 | [39093495068](https://github.com/JsonLord/event-scraper-github-actions/actions/runs/39093495068) | c89b7a3 | two known destinations plus free-admission Search candidate | 33 / 4 / 4 / 4 |

All three workflows succeeded. Machine summaries are
[r13-qualification-phase1.json](r13-qualification-phase1.json),
[r13-qualification-phase2.json](r13-qualification-phase2.json), and
[r13-qualification-phase3.json](r13-qualification-phase3.json). They were recovered
from sanitized base64 check annotations; no credentials or signed download URLs
are committed. Full sanitized diagnostic artifacts have seven-day retention.
Phase 3 artifact: ID `12124030313`, 236479 bytes,
SHA-256 `bca1e76a617a5e9a3f103173b7442ced489c24dc6b3d39168b51c72f226a5c50`.

Final observation: **18 October 2026, 05:25 CEST** (03:25 UTC). Repeated runs
observe overlapping events; discovery totals must not be added as unique events.
The phase-3 known destination seeds came from phase-1 public destination evidence,
not invented slugs. Its Search queries sought free-admission events; Search facts
were never accepted as event evidence.

## Rausgegangen diagnosis and repair

R1.2 phase 2's semantic listing retained disconnected dates, venue names and
prices, with zero usable event anchors/headings. The available evidence establishes
loss in the returned representation; it does not establish the provider's internal
cause. Reconstructing event titles from those fragments or URL slugs is unsafe.
Original JSON-LD, hidden client state and anchor attributes cannot be assumed to
survive semantic extraction. Fetch's requested `links: true` is not a guarantee
that an event card survives in semantic HTML. A listing HTTP 200 is not discovery.
No undocumented/private APIs or application state endpoints were queried.

Legitimate public detail pages were substantially better. Their semantic content
retained an h1, literal full date (`18. Okt 2026`), a start/end interval, and a
Location → Venue → name/address block. The previous general parser rejected
abbreviated month names, multiple headings and the interval's two times.
Some German destination URLs also redirected to English canonical destinations;
re-fetching an uncached locale alias previously exhausted direct HTTP attempts.

`rausgegangen_discovery.py` now supplies one bounded strategy shared by staging
and the production Raus listing entry point. It searches at most twice, accepts
only exact official HTTPS event paths, rejects query-bearing/lookalike/generic
URLs, collapses locale aliases, and attempts at most three independent destinations.
Search results supply URLs only. Direct bounded HTTP and robots policy precede
hosted Fetch; a run's blocked-host decision prevents repeated HTTP attempts.
Destination documents are cached under requested and final URLs. Production
caches its complete discovery result, including failures, for the process, so
per-day listing loops cannot restart the provider budget or host probing.
Production also applies the existing `observation()` matcher before accepting a
candidate. It never enters the generic browser/challenge fallback for this source.

The source-specific semantic parser isolates the literal header and venue block.
It requires a unique title, full date, one interval and Berlin location evidence.
The end time is not a second occurrence. A Berlin organizer in prose is insufficient.
Structured schema.org Event metadata remains supported where supplied; its
location.address.addressLocality is retained separately. Missing dates, ambiguous
headers and incomplete location evidence fail closed. No title reconstruction,
CAPTCHA solving, login, paid Agent/Browser, or circumvention proxy was used.

Prices, student discounts and inventory are deliberately UNKNOWN for the two Raus
matches. The captured page displays €41 for Gavin and €35–52 for Rattleskin;
Rattleskin explicitly says prices depend on dates. These are useful review clues,
not confirmed occurrence-bound offers in the overlay. The adapter excludes the
organizer body, shared price prose and conditional free-admission statements.
This conservative limitation is a release concern, particularly for a €20 budget
filter: an unknown-price published row must not be represented as affordable.

## Separate coverage metrics

| Final sample | Listing discovery | Candidate URL discovery | Exact occurrence matches | Verified source presence | Final materialized rows |
|---|---|---|---|---|---|
| Berlin Bühnen | 24 upcoming rows | yes | 1/1 | yes | 1 |
| ufaFabrik | 7 upcoming rows | yes | 1/1 | yes | 1 |
| Rausgegangen | failed / not repaired | yes: 19-URL union including two known seeds | 2/2 selected; 2/3 fetched destinations | yes | 2 |

Final total: 33 extracted upcoming occurrences, four selected, four exact matches
(100% of selected; not a 100% candidate success rate), four materialized rows.
All four selected occurrences have event-specific links and nonblank venues:
zero missing links, zero missing venues. One of the three Raus destinations was
rejected, before sample selection. The remaining candidate URLs were not fetched.
The sample contains **two distinct verified Raus occurrences**, not three.

`source_coverage_complete` now means at least one exact verified occurrence for
**every required source**, never merely a nonempty candidate sample. It is false
in phase 1 and true in phases 2/3. It does not mean successful listing discovery,
adequate release coverage or a complete source catalogue. Separate metrics expose
listing discovery, candidate URL discovery, selected/exact occurrence matches,
verified source presence and publishable row count. Later diagnostics additionally
count candidate URLs and attempted destinations. A regression covers the R1.2
misleading-positive case: candidates > 0 but verified Raus occurrences = 0.

## Exact final occurrences and unresolved evidence

All dates below are 18 October 2026; times are Europe/Berlin.

| Event | Time / venue | Identity | Confirmed price / student evidence | Inventory / event state |
|---|---|---|---|---|
| [Helga Schubert: Die Woche danach](https://www.berlin-buehnen.de/de/spielplan/helga-schubert-die-woche-danach/events/374730/) | 13:00 / Berliner Ensemble | strict title/date/time/venue | unknown / unknown | unknown / scheduled |
| [Ella Carina Werner](https://ufafabrik.de/veranstaltung/39991/ella-carina-werner) | 19:00 / Wolfgang Neuss Salon | strict title/date/time/venue | €12–22 / explicit student offer | unknown / unknown |
| [Rattleskin By DANCÆ](https://rausgegangen.de/en/events/rattleskin-by-danc-5/) | 18:30 / Cank Berlin | strict title/date/time/venue | unknown / unknown | unknown / unknown |
| [Gavin DeGraw](https://rausgegangen.de/en/events/gavin-degraw-6/) | 20:00 / Metropol Berlin | strict title/date/time/venue | unknown / unknown | unknown / unknown |

No free event, available ticket inventory, sold-out status or cancellation was
confirmed in the final sample. Free-admission Search returned Charlie Jeer, whose
page offered conditional free entry to a companion but lacked a usable performance
date/time and location. It was rejected, not labelled free or verified. Phase 2
also recorded two valid provider envelopes with `page_not_found`; HTTP 200 did not
convert those failures into successful extraction. Older summaries omit those
two failed candidate URLs, so their identities are not reconstructed here.

Missing-venue counterfactual replay matched Berlin Bühnen and both Raus rows via
canonical occurrence identity. ufaFabrik remained UNKNOWN in that counterfactual.
Known venue disagreement, a different date and the interval's end time all reject.
R1.2's real multi-performance Berlin fixture and cancellation-isolation regression
remain intact; this final small live sample did not add a multi-performance case.

## Budgets, provider compatibility and state

| Phase | Direct HTTP | Per-host Berlin / ufa / Raus | Fetch URLs / Search calls | Response bytes | Network / pipeline seconds |
|---|---|---|---|---|---|
| 1 | 9 | 4 / 3 / 2 | 4 / 2 | 494081 | 26.890 / 42.822 |
| 2 | 9 | 4 / 3 / 2 | 4 / 2 | 491515 | 15.356 / 27.187 |
| 3 | 9 | 4 / 3 / 2 | 4 / 2 | 494085 | 16.270 / 26.999 |
| R1.3 total | 27 | 12 / 9 / 6 across separate runs | 12 / 6 | 1479681 | 58.516 / 97.008 |

Each run stayed below the staging caps: 40 direct attempts, eight per host, 1.5 MB
per response, 25 MB aggregate, six Fetch URLs, four Search calls, shared 600-second
network deadline and 20-minute workflow deadline. The 12/9 aggregate host figures
span three runs, not a violation of the eight-per-host-per-run limit. Production
Raus discovery is narrower: three Fetch URLs, two Search calls, eight direct
attempts and a 540-second deadline, cached once per process. These requests are
also below the repository verifier caps (30 Fetch / 12 Search) and documented
provider free-service allowances. No additional live run is needed for the final
location/diagnostic hardening, which was validated against captured text offline.

Every provider call returned HTTP 200 with a valid response envelope. Two Fetch
URL errors were `page_not_found`; there were no observed allowance/auth/rate errors.
Across the three runs, Fetch calls took 0.957–7.908 s and Search calls 0.911–1.653 s.
No paid endpoints were invoked. Per-URL failure diagnostics and sanitized URLs are
preserved separately from verified occurrence metrics. Existing 401/402/403/429
fail-closed behavior, ttl=0 and bounded Fetch deadlines are unchanged.

In every phase, the actual production verifier wrote a timestamped temporary
overlay, round-tripped it through disk, and a second execution five minutes later
selected zero targets and preserved state without network calls. Materialization
used the shared production CLI. Eight-day expiration removed fresh verification
and free/status assertions. Input immutability and production file fingerprints
passed. Chromium search, ICS export and responsive rendering passed with zero page
errors in all three phases (2, 3 and 4 visible rows respectively).

## Validation and remaining errors

Final Python suite: **226 passed**, preserving the 219-test baseline and adding
coverage, URL, production-cache, captured-text, wrong-performance and city-evidence
regressions. Tests explicitly identify reconstructed DOM from captured sanitized
text; they do not claim it is an original provider HTML fixture. Original Berlin
and ufa provider-response fixtures remain unchanged. Local frontend Node checks,
frozen audit (475 → 464; nine quarantined and two deduplicated), shared build/schema
gate, verifier dry run, actionlint and Chromium smoke passed. The frozen-build
smoke showed 112 upcoming / 464 including past, search/ICS/responsive passed,
no JS errors. Offline CI is rerun on follow-up commits.

| Category | Remaining limitation / outcome |
|---|---|
| Extraction | Raus semantic listing still loses title/link associations; abbreviated detail-header parsing repaired. Header/date/venue identity works for two real occurrences. Prices deliberately unresolved. |
| Provider | Two `page_not_found` URL failures despite valid HTTP/schema. No observed quota failures; direct host 403 cached within each run. |
| Missing source evidence | Charlie Jeer has no usable occurrence/date/location. Conditional companion entry cannot establish free admission. No final live sold-out/cancelled or confirmed free Raus occurrence. |
| Workflow integration | Pipeline, persistence, TTL and browser checks pass. Legacy weekly writes remain outside daily activation gates. Actual repository flag values cannot be inspected with current permissions. |

Frozen October 11 records were neither rewritten nor treated as fresh evidence.
Current live samples use October 18 occurrences; production's frozen audit and all
three canonical JSON files remain unchanged. The staging materialized count is a
temporary technical output, not an approved production catalogue.

## Release recommendation

**A. Limited Berlin Bühnen + ufaFabrik release: conditional technical GO.** Both
sources retain real exact matches, live controls, pricing/student evidence where
available, and passing pipeline/browser checks. A first release should be an
explicitly approved fresh two-source dataset, with UNKNOWN inventory and prices
shown honestly. This is not permission to publish the existing full frozen data.
Before merge, confirm flags false/unset and pause the legacy weekly workflow if a
data-write freeze is required; separately approve the exact release artifact and
manual publication. No activation is performed here.

**B. Full three-source release: NO-GO.** Verified Raus source presence is repaired,
but listing discovery remains unavailable and the bounded sample is sparse, with
no confirmed Raus price/student/free evidence. One candidate is unusable and two
provider URL failures occurred. In particular, observed €35–52/€41 page clues
cannot silently become a claim that unknown-priced rows fit the €20 budget.

**C. Daily verification activation: NO-GO now.** Integration is technically GO for
the tested occurrences; activation requires explicit approval, authorized flag
inspection, an approved fresh production input, the weekly-write decision and a
separate Pages decision because daily persistence and deployment share one job.

Merge and deployment consequences and the unexecuted owner-controlled sequence
are documented in [R1.2 release controls](R12_RELEASE_CONTROLS.md).
