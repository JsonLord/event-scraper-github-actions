# Event Scraper System

A GitHub-powered event scraping system that replaces the original Heron-based implementation with GitHub Actions workflows and GitHub Pages for displaying results.

## Overview

This system scrapes event listings from various Berlin websites, filters for affordable events (≤20€), and provides a weekly overview. It has been adapted to run on GitHub Actions instead of the original Heron cron system.

## Key Changes from Original

1. **GitHub Actions Workflows**: Replaced cron jobs with scheduled GitHub Actions
2. **Desk Agent 2.0 Integration**: Replaced Firecrawl API calls with a Desk Agent 2.0 placeholder
3. **GitHub Pages Output**: Events are displayed via GitHub Pages instead of local reports
4. **Cloud-Native**: Designed to run entirely in GitHub's infrastructure

## Architecture

```
├── .github/
│   └── workflows/
│       ├── weekly-event-scraper.yml # The scraper. Sundays, 5PM UTC
│       └── jekyll-gh-pages.yml     # Rebuilds Pages when the data changes
├── scripts/
│   ├── generic_event_scraper.py    # The scraper every source runs through
│   ├── event_utils.py              # Date/price parsing, validation, dedupe
│   ├── score_events.py             # Ranking, categorisation, price filter
│   ├── recover_failed.py           # Second pass over sources that came back empty
│   └── rausgegangen_scraper.py     # Site-specific scraper (unused by the matrix)
├── data/
│   ├── events.json                 # Raw aggregate from the last run
│   └── events_scored.json          # Ranked/filtered output the page shows
├── docs/                           # GitHub Pages content (built each run)
│   ├── index.html                  # Main events display
│   └── events.json                 # Event data for frontend
└── requirements.txt                # Python dependencies
```

## Workflows

Scraping runs **weekly and only weekly**. There is one scheduled workflow.

### Weekly Event Scraper (`weekly-event-scraper.yml`)
- **Schedule**: Sundays at 5:00 PM UTC (`0 17 * * 0`), plus manual dispatch
- **Actions**:
  - Scrapes every source in the matrix in parallel, one job each, each
    writing `data/raw_<source>.json` and an HTML snapshot
  - Aggregates them, printing a per-source count so a source that has
    quietly stopped yielding is visible in the log
  - Runs a recovery pass over any source that returned nothing, walking from
    its listing to the individual event pages it links to
  - Scores, categorises and price-filters the result
  - Commits `data/events.json` + `data/events_scored.json` and deploys Pages

A run refuses to publish an aggregate that has collapsed to under a quarter
of the previous one, on the assumption that it was blocked rather than that
Berlin ran out of events.

### Pages Rebuild (`jekyll-gh-pages.yml`)
Not scheduled. Runs on push when the event data or the frontend changes.

### Reading a run's per-source counts

A zero is not automatically a bug. Sources legitimately report nothing when
the venue is between seasons or between shows, or when everything it lists
is over the price cap. The matrix comments record what is expected per
source; check those before treating a zero as a regression.

## Desk Agent 2.0 Integration

The original Firecrawl API calls have been replaced with a Desk Agent 2.0 integration in `scripts/firecrawl_validation.py`. 

**Note**: This is currently a placeholder implementation. To use a real Desk Agent 2.0 instance:

1. Set environment variables in your repository secrets:
   - `DESK_AGENT_HOST`: Your Desk Agent host
   - `DESK_AGENT_PORT`: Your Desk Agent port (default: 7860)
   - `DESK_AGENT_ENABLED`: Set to "true" to enable real calls
   - `DESK_AGENT_API_KEY`: If authentication is required

2. Modify the `call_desk_agent()` function in `scripts/firecrawl_validation.py` to match your Desk Agent 2.0's actual API specification.

## Setup

### For Development/Local Testing

1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt`
3. Configure `config.yaml` with your target URLs and scraper scripts
4. Set up `.env` file with any needed API keys
5. Run scripts directly:
   ```bash
   python scripts/weekly-event-scraper.py
   python scripts/firecrawl_validation.py
   python scripts/scraper_improvement_cycle.py
   ```

### For GitHub Deployment

1. Fork/create this repository
2. Go to Settings > Pages and set the source to `main` branch `/docs` folder
3. Enable GitHub Actions if not already enabled
4. The workflows will run automatically on their schedules
5. Your site will be available at `https://username.github.io/repository-name/`

## Configuration

### config.yaml
Defines the URLs to scrape and their corresponding scraper scripts:

```yaml
database:
  path: ~/event-scraper/events.db

urls:
  - name: "rausgegangen-berlin"
    url: "https://rausgegangen.de/en/berlin/tipps-fuer-heute/"
    script: "/path/to/scrapers/rausgegangen_scraper.py"
    categories: ["music", "dance", "social", "networking"]
    
  - name: "eventbrite-berlin"
    url: "https://www.eventbrite.de/d/germany/berlin/events/"
    script: "/path/to/scrapers/eventbrite_scraper.py"
    categories: ["networking", "social"]

scraper_settings:
  max_retries: 3
  timeout: 120
  price_filter: 20.0
  date_range_days: 14
```

## Data Flow

1. **Scraping Phase**: Individual scrapers (rausgegangen_scraper.py, etc.) extract events from websites
2. **Filtering & Storage**: Events are filtered (price ≤20€) and stored in events.db
3. **Validation Phase**: Desk Agent 2.0 (placeholder) validates scrapes and finds missed events
4. **Improvement Phase**: Scraper scripts are automatically updated based on validation results
5. **Presentation**: Events are exported to JSON and displayed via GitHub Pages

## Customization

### Adding a Site to the Weekly Scrape

Sites in the weekly run do **not** need a scraper of their own. Add one line to
the matrix in `.github/workflows/weekly-event-scraper.yml`:

```yaml
- { name: my_venue, url: "https://example.berlin/programm" }
```

`scripts/generic_event_scraper.py` handles it, trying every strategy over the
page and merging the results rather than stopping at the first that hits:

| Strategy | Reads |
| --- | --- |
| schema.org JSON-LD | `"@type": "Event"` blocks - carries price and venue |
| `<time datetime>` | machine-readable dates on cards with no date text |
| class-hint scan | cards whose class names say event/teaser/card/list-item |
| calendar headings | calendars that print the month once and a bare day number per row |
| date blocks | dated events on pages with no event-ish class names at all |
| WordPress REST | EventON / The Events Calendar plugin data, for calendars rendered client-side |

If direct HTTP yields no events, the scraper tries optional TinyFish free
Fetch (semantic HTML), then the existing optional CloakBrowser fallback.
TinyFish is capped at two fetched URLs per discovery process. The daily
verifier has its own stricter request, byte and provider budgets.

Set the optional Actions repository secret `TINYFISH_API_KEY`, or use a local
gitignored `.env` based on `.env.example`. Missing credentials leave the core
workflow usable. Only free Fetch/Search endpoints are used; no paid API or
Wallet action is authorized. Search results are candidates, never inventory
or price evidence. Published free limits can change; see the vendor references
in `spec.md`.

Requests are sent with a full browser header set - several Berlin sites answer
a bare `User-Agent` with 403.

`scripts/fetch_strategy_probe.py` (and the **Fetch Strategy Probe** workflow)
compares all of these per site and reports events kept per strategy, which is
how the tiers above were chosen. Run it in CI rather than locally: the answer
is IP-dependent.

Before adding a site, check it actually serves its programme: point the scraper
at it and see what comes back.

```bash
python scripts/generic_event_scraper.py \
  --url "https://example.berlin/programm" \
  --output /tmp/check.json --price-max 20 --date-days 7
```

A venue homepage is often the wrong URL - use the programme, Spielplan or
calendar page.

### Adding a Dedicated Scraper
1. Create a new scraper script in `scripts/` following the pattern of `rausgegangen_scraper.py`
2. Add an entry to `config.yaml` under `urls`
3. The scraper should:
   - Accept `--start-date` and `--end-date` arguments
   - Output JSON to a specified file
   - Follow the event schema: title, date, time, price, category, description, url, venue, source_url

### Modifying Validation Logic
Edit `scripts/firecrawl_validation.py` to:
- Adjust the Desk Agent 2.0 API calls
- Change validation criteria
- Modify how missed events are analyzed

## Maintenance

- Check the Actions tab for workflow runs and logs
- Review generated reports in the `docs/validation/` directory
- Monitor the GitHub Pages site for display issues
- Update scraper scripts as websites change
- Refresh the Desk Agent 2.0 integration when moving from placeholder to real implementation

## License

MIT
## R1 evidence and daily verification

Weekly discovery remains Sunday 17:00 UTC, with the source matrix, per-day
Berlin Bühnen horizon, low-aggregate guard and recovery stages. Daily
verification runs at 07:17 UTC, or manually. `data/events.json` remains canonical;
`data/event_verifications.json` stores compact observations by occurrence ID.
Weekly, daily and manual Pages workflows all call `scripts/build_page_dataset.py`.
The daily workflow deploys its own artifact: token-created commits do not trigger
ordinary push workflows. All three workflows share the `pages` concurrency group,
check out the latest branch, and fail on an external push race instead of
replacing newer observation data.

The daily limits in `config/verification_policy.json` cannot be raised above
40 targets, 40 HTTP attempts (including robots/redirects/retries), eight attempts
per host, 30 Fetch URLs, and 12 Search queries. Processing is sequential (one in
flight, below the limit of two). Responses are capped at 1.5 MB and the run at
25 MB; timeouts are 8 s connect / 12 s read. Robots policy failures deny retrieval.
Cross-host redirects remain unverified. Fetch/Search attempts consume their own
budgets even on failure, with at least one second between provider requests.
Account-wide usage by other applications cannot be controlled here.

Only exact folded title, occurrence date/time and venue matches verify a detail
link. A ticket button never proves availability. Missing venue/time evidence may
leave a real event unverified. Available reports expire after 12 hours, sold-out
and cancellation reports after 24 hours, prices after 48 hours, and discounts and
links after seven days. The browser checks expiry as well as the build. Failures
retain historical evidence; unknown/stale is never upgraded to available/free.

Use Python 3.11 (the existing PyYAML pin fails to build on Python 3.12):

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q
node tests/test_frontend.cjs
.venv/bin/python scripts/audit_events.py \
  --input tests/fixtures/events_scored_2026-10-11.json --output /tmp/r1-audit.json
.venv/bin/python scripts/verify_event_details.py --dry-run --now 2026-10-17T07:17:00Z
.venv/bin/python scripts/build_page_dataset.py --output-dir /tmp/r1-site --now 2026-10-17T07:17:00Z
.venv/bin/python scripts/audit_events.py --input /tmp/r1-site/events_scored.json --gate --output /tmp/r1-quality.json
# Optional full browser smoke when Chromium is installed:
.venv/bin/python scripts/smoke_pages.py --site /tmp/r1-site --output /tmp/r1-smoke
```

Tests never call live providers. Dry-run makes no requests and does not modify the
overlay. Normal verification needs public source access but no API key. Optional
`TINYFISH_ENABLED`, `TINYFISH_FETCH_ENABLED`, and `TINYFISH_SEARCH_ENABLED` default
to `true`, effective only with a key. Authentication/rate failures close the
provider for the run. No key is included in the build, frontend, artifacts or
usage diagnostics. Search snippets are never price/status evidence. Free vendor
limits are documented in `spec.md`; review current provider terms before enabling
live use. No paid Agent/Browser/Monitor endpoint, Wallet, proxy, challenge solving
or login is part of verification.

Review [the frozen audit and remaining release gates](docs/R1_REVIEW.md) before
merging or manually deploying. The historical plaintext credential must be
manually revoked/rotated by its owner; no history rewrite or secret rotation was
performed.
