# Quick Start

No API keys, no accounts, no services. The scraper is plain Python over HTTP.

## Setup

```bash
pip install -r requirements.txt
```

## Scrape one source

Any URL, straight from the command line — this is exactly what each job in the
weekly workflow runs:

```bash
python scripts/generic_event_scraper.py \
  --url "https://ausland.berlin/de/" \
  --output /tmp/check.json \
  --price-max 20 \
  --date-days 7
```

It prints what each extraction strategy found, then how many events survived
validation:

```
plain HTML: JSON-LD 0, <time datetime> 0, heuristic scan 15, calendar headings 0, date blocks 15
Found 16 candidate events from plain HTML
Price enrichment: found a price for 6/13 previously unpriced events
3 events kept for 2026-09-14..2026-09-21 (13 rejected as unusable or out of window)
```

Useful flags:

| Flag | Meaning |
| --- | --- |
| `--date-days N` | Keep events starting within N days (the workflow uses 7) |
| `--price-max N` | Drop anything dearer than N EUR (the workflow uses 20) |
| `--save-html --html-output PATH` | Save the fetched page, for working out why a source came back empty |
| `--price-enrich-limit 0` | Skip per-event detail fetches — much faster when you only care about titles and dates |

## Add a source

Add one line to the matrix in `.github/workflows/weekly-event-scraper.yml`:

```yaml
- { name: my_venue, url: "https://example.berlin/programm" }
```

Check it actually yields something first, with the command above. A venue's
homepage is often the wrong URL — use its programme, Spielplan or calendar
page. See the README for how the extraction strategies work.

## Recover a source that returned nothing

When a listing page gives up nothing, this walks to the individual event pages
it links to and reads those instead — an event's own page is usually far
better marked up than the listing:

```bash
python scripts/recover_failed.py \
  --aggregated docs/events.json \
  --raw-dir data --html-dir data/html \
  --output docs/events.json
```

It reports per site whether there was anything to work from:

```
ritterbutzke: 12 event pages -> 36 rows -> 1 kept for 2026-09-14..2026-09-21
werk9: no event pages linked - the source is empty, not blocked
berlin_buehnen: snapshot is a bot challenge, nothing to harvest
```

## Score and rank

```bash
python scripts/score_events.py \
  --input docs/events.json --output docs/events_scored.json --max-price 20
```

## Run the tests

```bash
python -m pytest tests/ -q
```

## Trigger the workflow

Actions → **Weekly Event Scraper** → Run workflow. It otherwise runs itself
every Sunday at 17:00 UTC, and only then — there is no daily job.
