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

If none of those find anything, it escalates — **Jina Reader first**, asked
for HTML so the same six extractors run again over a copy of the page fetched
from somewhere this network is not blocked, and **CloakBrowser** (stealth
headless Chromium) last.

That order is a measurement, not a preference. In probe run 34825099038,
venturecafeberlin.org refused the runner outright; CloakBrowser got its
challenge page and 0 events, while the Jina tier got the real page and the
event. Across the probe set Jina kept 33 events to CloakBrowser's 32, won two
sites to its none, and took 0.5–1.7s per site against 5–24s. The same site had
answered the *previous* runner normally — the blocking is intermittent, which
is exactly what makes a second route worth having.

Jina needs a `JINA_API_KEY` secret; without one it logs that it is skipping and
CloakBrowser still runs, so the pipeline degrades rather than breaks.

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