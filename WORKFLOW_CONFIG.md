# Weekly Event Scraper — configuration

One scheduled workflow, `.github/workflows/weekly-event-scraper.yml`, running
every **Sunday at 17:00 UTC**. There is no daily or weekday job.

## Sources

The source list is the `matrix.include` block in that file, one line each:

```yaml
- { name: ausland_berlin, url: "https://ausland.berlin/de/" }
```

Every source runs through `scripts/generic_event_scraper.py` — there is no
per-source scraper to write. Jobs run 4 at a time (`max-parallel: 4`) and
`fail-fast` is off, so one bad source cannot take down the run.

`__START_DATE__` and `__END_DATE__` in a URL are substituted at runtime with
today and today+7, for sources that take a date range as a query parameter.

Most matrix lines carry a comment recording what was measured from that
source and what to expect from it. Keep that up when you change one — it is
what stops a legitimate empty week being mistaken for a breakage.

## What a run does

1. **Scrape** — one job per source, each writing `data/raw_<name>.json` plus
   an HTML snapshot at `data/html/<name>.html`, uploaded as artifacts.
2. **Aggregate** — combines them into `docs/events.json`, printing a
   per-source count so a source that has quietly stopped yielding shows up in
   the log rather than only as a smaller total.
3. **Recover** — `scripts/recover_failed.py` takes every source that returned
   nothing, harvests the event-page links from its snapshot, and reads those
   pages directly. Bounded to 12 sites and 24 pages each.
4. **Guard** — a run that has collapsed to under a quarter of the previous
   aggregate refuses to publish and fails loudly, on the assumption that it
   was blocked rather than that Berlin ran out of events.
5. **Score** — `scripts/score_events.py` ranks, categorises and price-filters
   into `docs/events_scored.json`.
6. **Publish** — commits both files and deploys GitHub Pages.

## Filtering

- **Price**: 20 EUR cap. Free ranks best, up to 10 EUR is preferred. An event
  with no stated price is kept and scored neutrally, because most listings
  never state one; the scraper tries the event's own page before giving up.
- **Date range**: the next 7 days.
- **Streams**: the page splits out sport and networking; film and kids' events
  are excluded. See `scripts/score_events.py`.

## Event schema

```json
{
  "title": "Event title",
  "date": "2026-09-19",
  "time": "19:00",
  "price": 12.50,
  "category": "music",
  "description": "Event description",
  "url": "https://...",
  "venue": "Venue name",
  "source_url": "https://original-source.com"
}
```

## Troubleshooting

### A source returns 0 events

Not automatically a bug. Check, in order:

1. **Is the venue simply between seasons or between shows?** The recovery step
   distinguishes these: `no event pages linked - the source is empty, not
   blocked` means the site genuinely has nothing on. Sites with a real
   programme expose 12-193 event links.
2. **Is everything over the price cap?** Reinickendorf Classics extracts its
   whole season correctly and still reports zero, because the tickets are
   45-60 EUR.
3. **Is it blocked?** `snapshot is a bot challenge` in the recovery log, or an
   HTTP 403/405 in the scrape log, means the runner's datacenter IP is being
   refused. Only a residential proxy fixes that: set `HTTPS_PROXY` on the job
   and the scraper's session picks it up with no code change.
4. **Is the URL still right?** Download the run's `scrape-<name>` artifact and
   look at the saved HTML. Venue sites move their programme.

### A run is slower than usual

CloakBrowser (the rendered-DOM tier) is the expensive part and only runs when
plain HTTP yields nothing. The per-event price enrichment is next; it is
capped at 40 fetches per source and can be turned off with
`--price-enrich-limit 0`.
