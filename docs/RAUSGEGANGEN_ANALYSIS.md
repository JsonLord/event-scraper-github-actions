# Rausgegangen: access, extraction and browser analysis

Evidence reviewed: **29 October 2026**, Europe/Berlin. Working branch:
`codex/restore-before-tinyfish-search`; published code snapshot:
`4e508a7d5ce7e804ce9a5daccf4a3bd5f3a338e4`.

Rausgegangen currently contributes **zero verified occurrences** in the latest
qualification. The immediate gate is the robots policy observed on GitHub's
runner for our crawler, `BerlinEventEvidence/1.0`. A separate direct request
returned HTTP 403. Earlier evidence also demonstrates an extraction problem:
TinyFish's semantic listing representation lost event title/link associations.
These are separate failures, requiring separate remedies.

The exact **jo-inc Camofox Browser server has not been installed or tested**.
The existing optional implementation uses the underlying Python Camoufox package.
Its latest run stopped before browser launch because of robots policy. There is
therefore no evidence that either browser succeeds or fails at rendering the live
listing. Changing engines does not establish permission to crawl it.

This report reviews captured evidence and source code. The follow-up also checks
the current main branch and its existing weekly-run logs. No new Rausgegangen or
TinyFish requests were made and no production data was changed or deployed.
Separate, permitted Berlin Bühnen requests are documented in the
[event-link investigation](BERLIN_BUEHNEN_LINK_ANALYSIS.md).

## Evidence and its limits

| Evidence | Observation | What it establishes |
|---|---|---|
| [R1.3 report at its original branch commit](https://github.com/JsonLord/event-scraper-github-actions/blob/910ef257143fcf51d4d1601e190619198eb69da3/docs/R13_QUALIFICATION_REPORT.md), 18 October | Semantic listings retained disconnected dates, venues and prices, but no usable event title/link associations. Two independent detail occurrences were ultimately matched. | Detail extraction can work on suitable responses; listing discovery remained unresolved. Historical matches do not establish current access or fresh event coverage. |
| [Selective TinyFish run 40961000600](https://github.com/JsonLord/event-scraper-github-actions/actions/runs/40961000600), 29 October | Two Search calls returned HTTP 200 and valid schemas, in 1.684 s and 1.262 s. Ten distinct candidate URLs; three policy-checked destinations denied; zero Fetch URLs. | Search compatibility succeeded. Destination content, Fetch compatibility for these destinations and occurrence identities were not verified. |
| [Camoufox/date run 40963157968](https://github.com/JsonLord/event-scraper-github-actions/actions/runs/40963157968), 29 October | Camoufox package installed; robots guard stopped execution. Zero browser navigations, zero browser requests, zero Raus occurrences. | The policy guard worked. Browser rendering was not exercised. |
| Separate cloud direct check, recorded in [the selective trial report](SELECTIVE_SOURCE_TRIAL.md) | The supplied listing URL returned HTTP 403; the cloud robots response differed from the runner's policy. | Retrieval and policy can differ by execution environment. The cause of the variation and of the 403 is not established. |
| [Camofox upstream commit 39c8209](https://github.com/jo-inc/camofox-browser/tree/39c82094013480b373df6600d44c7f036f58356e) | README, package metadata, REST server, configuration and API specification reviewed. Package version 1.18.1 wraps Camoufox through Node.js. | Architecture and integration requirements only; no runtime or Raus compatibility qualification. |

A compact [machine-readable evidence extract](evidence/rausgegangen-analysis-2026-10-29.json)
preserves the latest run identities, Raus diagnostics, Search timings and recorded
robots policy. Full Actions artifacts have limited retention; this extract does
not contain the original event-page HTML or replace the historical reports.

## How the current main branch handles Rausgegangen

Main was fetched again for this comparison. Its head is
[`bab0e19072b966ae05f55342d29979b39d1eb4b5`](https://github.com/JsonLord/event-scraper-github-actions/commit/bab0e19072b966ae05f55342d29979b39d1eb4b5),
the 25 October weekly aggregate update. The latest completed weekly workflow is
[run 40225678325](https://github.com/JsonLord/event-scraper-github-actions/actions/runs/40225678325),
whose source jobs checked out `5160c32072c323bd99267de3d3d7a5a82803df03`.
The analysis distinguishes that completed run from a fresh October 29 test.

### Actual production path

The [weekly workflow](https://github.com/JsonLord/event-scraper-github-actions/blob/bab0e19072b966ae05f55342d29979b39d1eb4b5/.github/workflows/weekly-event-scraper.yml)
runs **`scripts/generic_event_scraper.py` for every matrix source**, including
Rausgegangen. It substitutes UTC today and today+7 in the same `eventsbydate`
URL template discussed above. It then applies its seven-day and €20 filters,
deduplicates, aggregates, scores, writes repository data and publishes Pages.

The [generic retrieval function](https://github.com/JsonLord/event-scraper-github-actions/blob/bab0e19072b966ae05f55342d29979b39d1eb4b5/scripts/generic_event_scraper.py)
tries, in executable order:

1. A direct HTTP session with browser-style headers and cookies, then the
   generic document extractors: JSON-LD, datetime markers, heuristic cards,
   calendar headings and date blocks.
2. Jina Reader **HTML**, if the direct path supplies no candidates and
   `JINA_API_KEY` is configured. It requests `X-Return-Format: html` and has a
   default two-request budget per scraper process. This is a configured fallback,
   not an observation that the latest Raus run needed it.
3. CloakBrowser rendered DOM if those paths supply no candidates. This is a
   different browser integration from both Camoufox and the Camofox REST server.

Executable order matters: some older comments still describe Jina as the last
tier, but the `scrape()` function invokes Jina before CloakBrowser. The separate
`scripts/rausgegangen_scraper.py` is a legacy Jina-markdown line scanner; it is
**not the weekly workflow's entry point**. That older file assigns the scrape
date and `Various` venue, so copying it would not solve exact occurrence identity.

Main also attempts bounded detail-page price enrichment for missing prices and
has a second-pass recovery step for empty sources. Recovery reads saved listing
snapshots, harvests same-host ordinary event anchors and tries detail JSON-LD.
These mechanisms improve extraction opportunities, but they do not apply the
current qualification's strict identity/performance/venue matcher.

### What the last main run actually achieved

The Raus job
[`121266401296`](https://github.com/JsonLord/event-scraper-github-actions/actions/runs/40225678325/job/121266401296)
records the following at 19:22 UTC on 25 October (20:22 CET):

```text
plain HTML: JSON-LD 0, <time datetime> 0, heuristic scan 189,
calendar headings 0, date blocks 2
Found 189 candidate events from plain HTML
Price enrichment: found a price for 21/48 previously unpriced events
150 events kept for 2026-10-25..2026-11-01
(39 rejected as unusable or out of window)
```

Thus **direct HTML worked in that run**; the successful listing did not require
Jina, TinyFish, CloakBrowser or Camofox. The optional browser fallbacks cannot be
credited with its success. This rules out the explanation that Raus necessarily
requires a new browser to produce any event records.

The committed main datasets expose a narrower quality result:

| Main snapshot metric | Aggregated `data/events.json` | Scored `data/events_scored.json` |
|---|---:|---:|
| All-source rows | 564 | 474 |
| Rows whose source URL is the Raus listing | 149 | 124 |
| Those Raus rows with a nonblank venue | 42 | 37 |
| Those Raus rows with a numeric price | 123 | 112 |
| Those Raus rows flagged as having a detail link | 149 | 124 |

One further event in each dataset has a Raus destination URL but an Orangerie
source URL; it is deliberately excluded from the Raus-source counts above.
The raw job's 150 retained rows and the aggregate's 149 source rows are different
pipeline measurements and must not be reported interchangeably. A link flag or
numeric price is an extraction result, not proof of successful destination
identity verification or ordinary public admission.

### Why main's success and this branch's failure can coexist

Main's generic fetcher does not perform a robots-policy check before collection.
It can also return a non-2xx body for extraction if it is not recognized as a bot
challenge. This branch's qualification instead uses the bounded `HTTP` client,
checks robots for `BerlinEventEvidence/1.0`, stops on denied/unknown policies,
caches host blocks and disables the legacy Jina/CloakBrowser fallbacks.

Consequently, main may collect usable HTML in an execution that our current
policy-aware run would decline. The runs also took place four days apart, with
different request identities and environments. The available evidence does not
isolate which factor caused the observed response differences. Main did not
record the robots evidence needed to establish permission retrospectively.

There is a representation difference too: main's successful raw HTML retained
enough card structure and URLs for the heuristic extractor; the historical
TinyFish semantic listing did not. This supports keeping a deterministic direct
HTML adapter for a **permitted** access path. It does not justify reconstructing
missing TinyFish titles or skipping the current robots gate.

**Assessment:** main has demonstrated historical extraction success, with major
venue gaps and weaker verification. It has not demonstrated that the current
access-policy and exact-evidence requirements are solved. Keep its useful dynamic
date URL and raw-HTML parsing lessons; do not copy the missing policy gate or
treat its October 25 prices/statuses as fresh verified newsletter evidence.

## 1. Robots permission and HTTP blocking are different

The runner captured `https://rausgegangen.de/robots.txt` with SHA-256:

```text
5f7beefec6a2f04e6adaa2d3607ae2154d4e7820caa55c1ef202f0e10734b99b
```

Its policy lists named search, AI, preview and SEO crawlers, followed by:

```text
User-agent: *
Disallow: /
```

Our identity is not among the named crawlers, so the qualification's policy
check denies both listing and detail requests. This is an application decision
to respect the site's published crawling rules; it is not a browser HTTP failure.
The three Search destinations recorded zero additional direct HTTP attempts
because the policy was already cached.

The separate HTTP 403 is a server-side refusal. It does not by itself identify
robots enforcement, a WAF, a particular browser fingerprint, location restrictions
or a required login. None of those causes was established by the captured result.
Similarly, different robots responses do not prove a specific CDN or geolocation
cause. Retain the response hash, execution environment, timestamp and actual agent
when comparing future observations.

Named permission for `GPTBot` or `ChatGPT-User` does not make our custom GitHub
scraper that crawler. We must not change the identity merely to obtain a more
permissive policy. Permission must cover our actual collection method. A provider
request is also not an automatic exception to the project's robots requirements.

## 2. The listing URL and date window

The requested URL is structurally consistent with the public listing template:

<https://rausgegangen.de/en/berlin/eventsbydate/?geospatial_query_type=CITY&lat=52.5&lng=13.405&city=berlin&active_city_name=Berlin&start_date=2026-11-01&end_date=2026-11-07>

It specifies HTTPS, the English Berlin listing, CITY query mode, Berlin city
labels, coordinates and ISO dates. The coordinates are near Berlin; query
parameters alone are not evidence that an individual event occurs in Berlin.
Because no usable listing was retrieved, we have **not validated the site's
actual interpretation of these filters**, inclusivity, pagination or completeness.

`scripts.raus_selective.listing_url()` builds this template from dates. The manual
workflow accepts `window_start` and `window_end` together, uses an inclusive local
window of at most eight dates within the next thirty days, and propagates it to
crawling and filtering. Without explicit dates it uses the current Berlin date
through seven days later. Historical report dates must not be reused as fresh
qualification inputs after they expire.

The November 1–7 run published 341 review rows from other sources, all within that
window. That validates our downstream date restriction, not Rausgegangen's remote
filter behavior. Raus contributed zero rows.

## 3. Semantic extraction loses relationships

TinyFish Fetch returns cleaned semantic HTML. A successful HTTP response or valid
provider envelope does not guarantee preservation of scripts, attributes, anchors
or the relationships between event cards. The earlier listing evidence contained
dates, prices and venues without usable event headings/links. It cannot support
reconstructing titles from slugs or assigning disconnected prices to nearby cards.
The captured representation demonstrates the loss; it does not establish the
provider's internal reason for it.

Historical detail pages performed better. R1.3 matched Rattleskin By DANCÆ and
Gavin DeGraw using a literal title, full date, start/end interval and Berlin venue
block. Two matches demonstrate a narrow successful path, not broad listing or
publication coverage. Their October 18 dates are now past.

The current source-specific adapter supports structured Event metadata first,
then a narrowly isolated Raus detail header. It requires an event-specific official
URL, unique title, full date, unambiguous time and Berlin location evidence.
An interval's end time is not another performance. Shared organizer prose,
related events and date-dependent price descriptions cannot establish a matching
occurrence's price or ticket inventory.

The parser is intentionally restrictive. If a new layout omits or renames the
expected header/location block, it should produce no verified occurrence rather
than guess. Such failures need captured permitted fixtures before widening it.

## 4. Camofox Browser versus Camoufox

| Component | Role | Current qualification |
|---|---|---|
| Chromium | Smoke tests our own static site and its controls. | UI checks passed; this does not qualify Raus retrieval. |
| Python `camoufox==0.5.8` | Existing optional Firefox-based listing renderer, selected by `raus_browser=camoufox`. | Package installed; live navigation blocked by policy. Positive renderer tests use a fake browser. |
| [`jo-inc/camofox-browser`](https://github.com/jo-inc/camofox-browser) | Node.js REST server around the Camoufox engine, with accessibility snapshots, tab operations and extraction APIs. | Source reviewed; server not installed, launched or integrated. |

Camofox could provide a convenient browser service and could help diagnose a
JavaScript-rendered listing **after permitted access is established**. Its
anti-detection claims are upstream claims, not results measured on this source.
Because both implementations use Camoufox, the REST wrapper is not evidence of
a different rendering engine or a solution to the observed permission gate.

Accessibility snapshots may retain titles and links better than the previous
semantic HTML, but that is untested here. Snapshots can also omit JSON-LD and
attributes; either representation needs occurrence-level fixtures and matching.

An actual Camofox integration would need pinned dependencies, Node.js 22 or newer
for the reviewed version, loopback-only binding, isolated temporary state,
telemetry disabled (`CAMOFOX_CRASH_REPORT_ENABLED=false`), and equivalent robots,
redirect, request, response-size and deadline controls. It must not assume that
the existing Python renderer's per-request restrictions transfer to a REST service.
Cookie import, persistent login, search macros, proxy rotation and CAPTCHA flows
are unnecessary for this qualification and outside its scope.

## 5. What TinyFish can and cannot currently contribute

Search can find legitimate event-detail URLs despite failed listing discovery.
The selective trial successfully exercised that function within its two-call cap.
Search titles and snippets remain candidates, never proof of dates, venues,
ordinary admission, student discounts or ticket availability.

Fetch could supply useful detail content if an allowed destination cannot be read
directly. The current implementation requires direct HTTP first and a permitted
destination before Fetch. All three checked candidates failed the policy gate,
so **zero Fetch requests were made**. Their extraction outcome is untested, not a
provider failure. No allowance, authentication or rate-limit error was observed
in the two successful Search calls; no conclusion about remaining account quota
can be drawn from that.

Retain Raus-only allowlisting, run-local blocked-host and document caches, and
the current limits of two Search calls and three destination Fetch URLs. These
are request caps, not proof of available free quota. No paid Agent/Browser endpoint
or new live provider test is needed to write this report.

## 6. Coverage and newsletter consequences

The selective trial produced the following distinct outcomes:

| Metric | Measured result |
|---|---:|
| Usable Raus listing discovery | Failed |
| Distinct candidate URLs discovered by Search | 10 |
| Candidate destinations policy-checked | 3 |
| Candidate destinations denied by policy | 3 |
| Destination documents retrieved / Fetch URLs consumed | 0 / 0 |
| Exact occurrences matched | 0 |
| Verified Raus source presence | No |
| Publishable verified Raus occurrences | 0 |

An exact-match percentage is **not applicable** when no destination occurrences
were retrieved and tested. Zero missing links or venues in an empty dataset is
not successful coverage. The latest browser run also produced no Raus rows.

No current Raus price, student discount, sold-out/cancelled state or ticket
inventory was verified. The earlier detail matches deliberately left price and
inventory UNKNOWN. UNKNOWN price cannot qualify for Community/newsletter content:
the agreed rule requires explicit ordinary public admission of at most €5,
plus an eligible publicly accessible event or substantial cultural/community host.
Student-only, companion-only or conditional free entry cannot establish that rule.
Source identity alone must neither qualify nor exclude an otherwise evidenced
event. Original venue pages may establish eligible events independently.

## 7. Recommended recovery sequence

1. **Establish a permitted access path.** Seek an official feed, documented public
   API, export or explicit crawling permission covering our actual identity and
   GitHub execution. Availability of such a feed/API has not been established.
   A sitemap declaration is a discovery lead, not permission to crawl its content.
2. **Use permitted original venue/organizer pages in parallel.** Discover and
   verify those sources independently, retain their provenance and avoid counting
   them as verified Raus coverage. Search can provide leads within existing caps.
3. **Diagnose retrieval only after the policy gate passes.** Make one bounded
   direct request; cache a 403/429 decision within the run. If browser evaluation
   is permitted, compare one listing response from the existing Camoufox adapter
   with the exact Camofox server. Stop at access challenges. Capture sanitized
   status, timing, final URL and representation statistics.
4. **Qualify extraction against several independent occurrences.** Confirm title,
   date/time, event URL and Berlin venue from destination content. Include multiple
   dates and a multi-performance page where available. Keep prices/statuses UNKNOWN
   unless explicit evidence binds to that same occurrence; test rejection of nearby
   cards, other dates, conditional discounts and unrelated negative statuses.
5. **Measure the entire publication path.** Report listing, URL discovery, attempted
   destinations, exact matches, verified source presence and final publishable
   counts separately. Replay sanitized fixtures offline, then run manual staging
   with temporary outputs and provider limits before any release decision.

The existing 199-test result belongs to the published Camoufox/date code run.
The follow-up Berlin Bühnen adapter and captured-fixture tests bring the local
suite to **205 passing tests**. That change addresses missing custom-element
links, not Raus access. No new live Raus/provider qualification is represented
as having occurred during this comparison.

## Decision

**Rausgegangen production coverage: NO-GO on current evidence.** Search discovery
works, but current destination access and verified publication coverage do not.
**Camofox live rendering: unqualified**, not proven ineffective. The highest-value
next step is a permitted source/feed path, followed by bounded retrieval and
occurrence extraction tests. A browser swap alone does not resolve the issue.

Other source qualification remains separate. This report provides no release
authorization, does not change PR #33, and does not enable schedules or deployment.
The existing main-branch Sunday weekly writer remains capable of overwriting a
branch preview; its separate release-control risk is recorded in
[the restored-branch qualification](RESTORED_BRANCH_QUALIFICATION.md).
