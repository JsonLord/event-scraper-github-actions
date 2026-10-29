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

This report reviews captured evidence and source code. Preparing it made no new
Rausgegangen or TinyFish requests and did not deploy or change production data.

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

The existing 199-test result belongs to the published Camoufox/date code run;
this documentation update adds no executable behavior. No further live requests
or test runs are represented as having occurred during report preparation.

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
