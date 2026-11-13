# Community picks — the weekly editorial handoff

A separate, human-approved selection of free and low-cost Berlin events,
published at
`https://jsonlord.github.io/event-scraper-github-actions/community/`.

This folder is the **canonical handoff** between three parties that never run
at the same time:

| Party | Writes | Reads |
| --- | --- | --- |
| Discovery (the scraper) | `data/events.json`, `data/events_scored.json` | — |
| Candidate preparation (`scripts/community_prepare.py`) | `candidates/<week>.json`, `reviewed/<week>.md` | the aggregate |
| A human editor | `reviewed/<week>.json` | the summary, the official pages |
| Promotion (`scripts/community_promote.py`) | `approved/<week>.json`, `latest.json`, `archive/index.json` | candidates + decisions |
| The browser | — | `latest.json` only |

Two rules are enforced in code, not by convention:

1. **Nothing is public without an explicit approval.** `latest.json` is only
   ever written by the promotion tool, from events whose ids appear in a
   review file with `"decision": "approved"`. A high score approves nothing.
2. **An unknown price is never published.** `publication_problems()` refuses
   `unknown` and `needs_verification` outright, so no ranking can push an
   unverified price onto the page.

## What this pipeline deliberately does not do

No Gmail, WhatsApp, PostgreSQL, server backend, DSPy or autonomous LLM step.
The weekly editorial judgement is made by a person editing a JSON file in Git;
GitHub Actions is the storage and publication layer. That is the phase-1
design, not a gap in it.

---

## Repository findings (why the extension looks like this)

Read from the code as it stands, not from the older README prose.

### How the scraper runs

`weekly-event-scraper.yml` defines **one matrix entry per source** and runs
`scripts/generic_event_scraper.py` once per leg. Each leg writes
`data/raw_<source>.json` and an HTML snapshot at `data/html/<source>.html`,
uploads both as a build artifact, and exits. `max-parallel: 4`, `fail-fast:
false`, so a dead source costs its own leg and nothing else.

`generic_event_scraper.py` is not a single strategy. `scrape()` tries tiers in
order — plain HTTP GET, then Jina Reader HTML, then a CloakBrowser render —
and a tier is only accepted if the body is not an anti-bot interstitial
(`is_bot_challenge()`). Within one accepted document, `scrape_document()` runs
**all** extractors and merges them, so a page whose JSON-LD describes four
events does not hide its other fifty cards:

| Extractor | Reads |
| --- | --- |
| `extract_jsonld_events` | `@type: *Event` in `application/ld+json`, `@graph` included |
| `extract_time_element_events` | `<time datetime>` markers and the card around them |
| `extract_heuristic_events` | elements whose class hints at a listing row |
| `extract_calendar_events` | calendars that print a month once and a day number per row |
| `extract_block_events` | pages built from anonymous blocks (no event-ish class at all) |
| `fetch_wordpress_events` | `/wp-json/wp/v2/ajde_events` and The Events Calendar REST API |

`--date-horizon` (opt-in per source) re-runs the whole chain once per day with
a date parameter injected, merging the days. Only sources measured to honour
the parameter use it.

The scraper also carries a dedicated evidence model
(`scripts/ticket_evidence.py`), source-specific card parsers
(`scripts/raus_html.py`, `scripts/official_source_adapters.py`) and a
redacted-URL fetch client (`scripts/tinyfish_client.py`). Image extraction
hooks into all of them: the generic extractors call `_attach_card_image`,
while the dedicated parsers - which select their own card containers and
return plain dicts - get `_attach_listing_images` / `_attach_document_images`
applied to their output, matched by each row's own event URL. Artwork is
attached; prices, dates, identities and gates are untouched.

### How detail pages are recovered

Two paths, both walking *from a listing to an event's own page*:

* `enrich_missing_prices()` — for a row whose card stated no price, fetch the
  row's detail URL and read the price there (`_price_from_detail_page()`).
  Capped by `--price-enrich-limit` (default 40 per source).
* `scripts/recover_failed.py` — after aggregation, for a source that returned
  **nothing at all**: re-read its saved snapshot, harvest same-origin detail
  links, fetch up to 24 of them concurrently, and validate what they say. It
  needs no API key and replaces a Jules session that never once completed.

The new image pass mirrors the first path exactly (`enrich_missing_images()`),
with its own smaller cap so a source that never prices its events cannot
spend the whole budget on price lookups.

### Price and date normalisation

`event_utils.py` is the single place these decisions live.

* `parse_price()` → `float`, `0.0` for explicitly free, **`None` when not
  stated**. `None` is load-bearing: the docs there record that defaulting
  unknown prices to `0` sent placeholder rows to the top of the ranking.
* `DEFAULT_MAX_PRICE = 20.0` is the *personal* pipeline's cutoff.
* `normalize_date()` / `parse_date()` return `None` rather than today's date
  when nothing parses, so a bad row is dropped instead of mis-dated.
* `parse_time()` refuses to read a dotted date as a time.

### How the aggregate is persisted

`aggregate-and-deploy` downloads every `scrape-*` artifact into `data/`,
concatenates the per-source `events` arrays, then runs recovery, then copies
the result over `data/events.json` — **refusing** to publish if the new total
is under a quarter of the previous one (a blocked run, not an empty city).
`score_events.py` then writes `data/events_scored.json`.

### How the Pages artifact is assembled

`.github/workflows/jekyll-gh-pages.yml` builds `_site` and deploys it with
`actions/upload-pages-artifact` + `actions/deploy-pages`. The weekly workflow
also deploys, from `_site`. Both now call one assembler,
`scripts/build_pages_site.py`, which copies an explicit allowlist and refuses
to publish `candidates/` or `reviewed/`.

### Fields the existing frontend actually uses

`web/index.html` reads `events_scored.json` and depends on:
`title, url, source_url, has_detail_link, venue, description, date, time,
price, price_label, score, stream, matched_categories, category`.
The community record is a **separate shape** — nothing in `web/index.html`
reads it, and nothing in `latest.json` depends on the personal scorer.

---

## The weekly loop

### 1. Prepare candidates (manual, or later on a schedule)

```
python scripts/community_prepare.py \
  --events data/events.json \
  --scored data/events_scored.json \
  --newsletter-root community \
  --week-start 2026-11-16
```

or run the **Community candidates** workflow. It writes:

* `candidates/<week>.json` — every proposed event, with its verification record
* `reviewed/<week>.md` — the review summary a human reads

The week defaults to the **next** Monday–Sunday in Europe/Berlin, because an
issue prepared on a Sunday covers the Monday that follows it.

> **The aggregate only covers what the scraper last ran for.** If the summary
> says `no events discovered for <range>`, the scrape window has to be widened
> first — a future week is empty because nothing has been scraped for it, not
> because Berlin has nothing on.

### 2. Review

Read `reviewed/<week>.md`. It lists each proposal with its date and time,
category, venue and district, verified price, one-line reason, official link,
image availability and verification outcome — plus a separate unresolved
section for anything that could not be checked.

Then write `reviewed/<week>.json`:

```json
{
  "issue_week_start": "2026-11-16",
  "reviewed_by": "your name",
  "decisions": [
    { "event_id": "ce-…", "decision": "approved" },
    { "event_id": "ce-…", "decision": "rejected", "note": "wrong date on the official page" }
  ]
}
```

Only ids that appear in the candidate file are accepted; a decision naming an
unknown id fails the whole promotion, because it means the file being reviewed
is not the file being published.

### 3. Promote

```
python scripts/community_promote.py --newsletter-root community --week-start 2026-11-16
```

or run the **Promote approved community issue** workflow (`dry_run` first, if
you like). It validates every approved event against the publication rules,
writes `approved/<week>.json`, `latest.json` and `archive/index.json`, and
commits them. The commit to `community/latest.json` is what triggers Pages.

Set `--require-complete` / the workflow's `require_complete` input for
all-or-nothing behaviour: by default one unpublishable event is excluded and
reported, rather than blanking the week.

---

## Publication rules

An event may appear publicly only when **all** of these hold
(`community_issue.publication_problems`):

* it falls inside the issue week, Monday–Sunday, Europe/Berlin
* its title and date are `match` or `corrected` against its official page
* its verification status is `matched` or `corrected` — not `not_confirmed`
* it is not marked cancelled or postponed
* its entry price is **confirmed**: free, or paid at €15.00 or less
* it has an event URL and a named venue

Availability is deliberately *not* required: a page with no sold-out marker has
not confirmed that tickets remain, so requiring it would block every event.

## Price vocabulary

`scripts/price_status.py` owns the shared contract. Every record carries one
canonical `price_status`, so no consumer has to work out which pipeline
produced it:

| status | meaning | entry price | publishable |
| --- | --- | --- | --- |
| `confirmed_free` | free entry, established by evidence | 0 | yes |
| `confirmed_paid` | one confirmed price | that price | if ≤ €15 |
| `range` | a confirmed low-to-high span | the low end | if low ≤ €15 |
| `donation_based` | pay-what-you-want | not applicable | yes, with a note |
| `needs_verification` | source defers ("on request", "TBA") | unknown | no |
| `unknown` | no price stated | unknown | no |

An event is *selectable* in every state - an unsettled price is exactly what
verification is for - but only the confirmed states are publishable.

Two invariants, both inherited from the pipelines that predate the contract:

1. **A bare numeric zero is not evidence of free entry.** A `price: 0` that
   nothing corroborates is `unknown`, because several sources emit zero when
   they failed to find a price. This is what stops an unverified price being
   published as Free.
2. **Absence never becomes certainty.** A missing number is never upgraded to
   a confident status, and no status can invent a number that is not there.

### How a bare number is read

Three cases, deliberately not treated alike:

| case | status | why |
| --- | --- | --- |
| present **positive** number, no other evidence | `confirmed_paid` | it arrived via a JSON-LD offer, a price regex over card text, or an official detail page — each already read a number the source published |
| **missing** number | `unknown` unless text settles it | `Eintritt frei` → confirmed free, `auf Spendenbasis` → donation, `Preis auf Anfrage` → needs verification; silence stays unknown |
| bare **zero**, nothing corroborating | `unknown` | several sources emit `0` when they failed to find a price |
| zero **with** free text or a structured offer of 0 | `confirmed_free` | the proof is what makes it free |

The positive-number rule is a pipeline decision inherited from both branches,
not an accident; `tests/test_price_status.py` pins it so it cannot drift. The
bare-zero rule is the load-bearing half: a zero is what a *failed* scrape looks
like, while a positive number is what a *successful* one looks like.

**Migration.** Records already on disk keep working. `price_status.py` maps the
historical evidence spellings one way - `free` → `confirmed_free`, `known` →
`confirmed_paid` - and passes `range`/`unknown` through unchanged. It never
downgrades a current record, so reading and re-writing is lossless.

**Provenance.** Canonicalising the status does not discard the evidence behind
it. Records keep `offers`, `free_admission_confirmed`, `price_min`/`price_max`,
`evidence` and `observed_at`, and community records carry a `price_provenance`
block naming the pipeline and model that established the status. The status
says *what is known*; the provenance says *how*.

### Publication completeness

`require_complete` is off by default and stays that way. A week publishes every
eligible approved event, excludes any that break a publication rule, and
reports each exclusion with its reason. The approved issue records this
explicitly:

```json
"publication": {
  "approved_requested": 12, "published": 11, "excluded": 1,
  "complete": false, "policy": "partial",
  "exclusion_reasons": ["price_unknown"]
}
```

One broken event never blanks a week, and an incomplete week is never silently
incomplete. `--require-complete` remains available for all-or-nothing runs.

### Identity namespaces

`ticket_evidence.occurrence_id()` assigns `sha256:…` ids, and the aggregate may
carry one. Community files require `ce-…` ids, so `event_record()` accepts only
a `ce-` id and mints its own otherwise. The id has to mean one thing across
candidates, reviewed and approved, because an approval names it.

## Category vocabulary

Broad and non-personal, deliberately not the personal scorer's keyword table:

`electronic`, `music`, `nightlife`, `arts`, `culture`, `workshops`, `outdoor`,
`sports`, `markets`, `community`, `other`.

Matching is whole-word only. A suffix rule would let `market` match
`Marketing`, and there is no automatic way to tell an English derivative from
a German compound — so compounds like `technonacht` are listed explicitly and
anything unlisted falls into `other`. A visible miss beats a confident
mis-file.

## Selection policy

`scripts/community_select.py`, separate from `score_events.py`:

1. price band — free, then donation, then cheap paid
2. verifiability — a confirmed row outranks an unconfirmed one
3. listing quality — a real event page, a stated time, a venue, a description
4. variety — each pick makes its category and district less valuable for the
   next, so a shortlist cannot be ten techno nights in Friedrichshain

The result is capped at 35 and is **never padded**: a thin week returns a short
list, and the summary says so.

## Verification contract

`scripts/community_verify.py` fetches each selected event's own page and
compares field by field. Per field: `match`, `corrected`, `not_confirmed` or
`rejected`. The official page wins every conflict, and corrections are applied
to the record before it is written.

`not_confirmed` is not a soft pass. An unreachable page, a bot challenge or a
silent page all leave the field unconfirmed, and unconfirmed identity or date
blocks publication.

## Files

```
community/
├── README.md                            this file
├── schema/
│   ├── community-event.schema.json      the issue contract (candidates → approved)
│   └── reviewed-decision.schema.json    the human decision file
├── candidates/<week>.json               proposed events + verification (draft)
├── reviewed/<week>.json                 human decisions (draft)
├── reviewed/<week>.md                   generated review summary (draft)
├── approved/<week>.json                 immutable published issue
├── latest.json                          public copy of the latest approved issue
├── archive/index.json                   published weeks and their URLs
├── archive/index.html                   browsable archive
├── index.html                           the community page
└── assets/{community.css,community.js}
```

`<week>` is the ISO Monday of the issue week, e.g. `2026-11-16`.

## Tests

```
python -m pytest tests/test_community.py tests/test_community_pipeline.py \
                 tests/test_image_extraction.py tests/test_pages_artifact.py
```

They cover the week boundary (a Sunday belongs to the week that started six
days earlier), stable ids across tracking parameters and recurring dates, the
€15.00 / €15.01 boundary, unknown-price handling, category non-collisions,
verification status outcomes, the refusal to publish an unapproved event, the
refusal to publish at all without a review file, and the artifact containing
both pages while containing no draft data.
