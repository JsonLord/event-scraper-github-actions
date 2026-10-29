# Berlin Bühnen: why event links opened the programme listing

Investigated 29 October 2026, Europe/Berlin, on
`codex/restore-before-tinyfish-search`. The existing published site uses
`4e508a7`; the repair described here is a branch change, not a new deployment.

## Finding

**The HTML already contains specific event URLs. The generic extractor ignores
their custom element and falls back to the programme listing.** This is a
deterministic parsing bug, separate from Rausgegangen's current policy gate.
A browser or paid provider is unnecessary to read these links in the captured
direct HTML.

The public listing uses markup such as:

```html
<hylo-router-link class="... event-list-item"
  href="/de/spielplan/keine-panik-resilienz-polykrise-fiff-konferenz-2026/events/376780/">
  <!-- One card's literal title, datetime and venue -->
</hylo-router-link>
```

`_best_detail_url()` in `scripts/generic_event_scraper.py` searches descendants
with `find_all("a", href=True)`. It does not read the containing
`hylo-router-link`'s own `href`. The datetime extractor likewise searches for an
ordinary anchor when deciding where its card ends. Mobile/desktop copies and
generic heuristic/date-block extraction can consequently yield duplicate or
incomplete variants, with no specific link.

The fallback returns `source_url`, originally a dated schedule request. After
merging the date horizon, `scrape_date_horizon()` deliberately rewrites those
dated listing fallbacks to the undated `/de/spielplan` URL. That normalization
prevents false detail-link flags; it does not remove correctly extracted event
URLs. `validate_event()` marks the fallback `has_detail_link: false`.

The frontend then correctly renders an unlinked title plus **“on listing page”**,
which points to `/de/spielplan`. The link opens the programme landing page
because that is the URL in the dataset. The observed problem is not a JavaScript
rewrite of a correct event URL, and the targeted detail check below did not
redirect to the homepage.

## Scope in existing data

| Snapshot | Berlin Bühnen rows | Missing event links |
|---|---:|---:|
| Main `bab0e190`, aggregate | 214 | 214 |
| Main `bab0e190`, scored | 157 | 157 |
| Published November 1–7 qualification, source candidates | 302 | 302 |
| Same published qualification, final scored review rows | 199 | 199 |

These are different datasets and pipeline stages; the counts are not additive.
The old source report's 302 candidates were not 302 independently verified events.
This bug is present on main as well as on the restored branch.

## Targeted live investigation

Five bounded direct HTTP requests were made: two robots-policy reads, two listing
reads and one detail read. All returned HTTP 200, with robots checked before page
access. No TinyFish, Jina or browser request was made for this investigation.
The [machine-readable evidence](evidence/berlin-buehnen-link-analysis-2026-10-29.json)
preserves response/fixture hashes, request diagnostics and extracted records.

| Public page | Source event cards | Repaired card records | Specific links / nonblank venues |
|---|---:|---:|---:|
| `/de/spielplan/?date=2026-11-01` | 24 | 23 | 23 / 23 |
| `/de/spielplan/?date=2026-11-02` | 24 | 24 | 24 / 24 |

Both responses contain `bb-page-list next="2"`: they are first pages, not a complete
two-day catalogue. No pagination completeness claim is made. One November 1 card
has conflicting mobile/desktop headings: “Jazzfest Berlin 2026 Matthias Muche
BONECRUSHER” versus “Matthias Muche BONECRUSHER”. It is conservatively rejected
rather than silently choosing an identity.

The first repaired link was fetched separately:

<https://www.berlin-buehnen.de/de/spielplan/keine-panik-resilienz-polykrise-fiff-konferenz-2026/events/376780/>

It returned HTTP 200 at the same URL. Its JSON-LD names the same event and
`2026-11-01T10:00:00+01:00`. The listing names Theater im Delphi; its JSON-LD
venue is only **“Bühne”**, with a Berlin street address. Thus the link and
title/date/time are corroborated, but the current strict venue matcher must not
be reported as a successful full match for that sample. Improving generic venue
metadata handling is a separate verification task; this repair does not weaken
the matcher or promote prices/inventory.

## Repair and regression coverage

`scripts/official_source_adapters.py` now reads
`hylo-router-link.event-list-item[href]` only on the official Berlin Bühnen host.
Each record uses its own exact HTTPS event path, agreeing mobile/desktop h3
titles and datetime markers, and the first desktop venue h4. Later h4 subtitles
such as “Ensembleproduktion” do not replace the room name. Ticket-vendor links
inside the card never replace the official event URL.

Missing or conflicting identity fields and credential-bearing, external,
query-bearing or non-event destinations fail closed. Price remains UNKNOWN:
the existence of a “Tickets” link is not an admission-price or inventory claim.
The unchanged normalization, date-horizon, scoring and frontend paths consume
these records. No generated production JSON is committed.

Six new tests replay sanitized real card fragments from both dates and cover
correct title/time/venue/link binding, repeated responsive markup, subtitle
isolation, unsafe/missing links, ambiguous identities, cross-date URL preservation
and source isolation. The full local suite passes: **205 tests**. Fixture
provenance is in [the fixture README](../tests/fixtures/official_programmes_2026-10-29.README.md).

This is **47/48 captured-card extraction success**, not an exact-match verification
rate or complete publication coverage. Pages still serves the previous snapshot
until an explicitly selected branch build is published. No merge, scheduling or
production-data change is part of this investigation.

See also [the Rausgegangen analysis](RAUSGEGANGEN_ANALYSIS.md): its main-branch
comparison separates successful historical direct retrieval from current policy
and semantic-representation limitations.
