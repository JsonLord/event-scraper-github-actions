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
│       ├── weekly-scraper.yml      # Main scraping workflow (Mon-Fri 5PM UTC)
│       ├── validation.yml          # Daily validation workflow (Daily 5PM UTC)
│       └── improvement-cycle.yml   # Weekly improvement workflow (Sun 6PM UTC)
├── scripts/
│   ├── weekly-event-scraper.py     # Main orchestrator
│   ├── firecrawl_validation.py     # Modified to use Desk Agent 2.0 (placeholder)
│   ├── scraper_improvement_cycle.py # Self-improvement logic
│   ├── rausgegangen_scraper.py     # Berlin events scraper
│   └── eventbrite_scraper.py       # Eventbrite scraper (to be implemented)
├── data/
│   ├── events.db                   # SQLite database (generated per run)
│   └── weekly-report.md            # Weekly summary
├── docs/                           # GitHub Pages content
│   ├── index.html                  # Main events display
│   ├── events.json                 # Event data for frontend
│   └── validation/                 # Validation reports
├── config.yaml                     # URL/script mappings
└── requirements.txt                # Python dependencies
```

## Workflows

### Weekly Scraper
- **Schedule**: Monday-Friday at 5:00 PM UTC (matches original cron: `0 17 * * 0-4`)
- **Actions**: 
  - Runs the main event scraper
  - Generates events.json for GitHub Pages
  - Deploys updated site to GitHub Pages
  - Uploads logs as artifacts

### Validation
- **Schedule**: Daily at 5:00 PM UTC (matches original cron: `0 17 * * *`)
- **Actions**:
  - Runs validation using Desk Agent 2.0 (placeholder)
  - Saves validation reports
  - Updates GitHub Pages with validation summary

### Improvement Cycle
- **Schedule**: Sunday at 6:00 PM UTC (matches original cron: `0 18 * * 0`)
- **Actions**:
  - Runs scraper improvement analysis
  - Automatically commits improved scraper scripts
  - Generates improvement reports

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
the matrix in `.github/workflows/weekly-jules-review.yml`:

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

If none of those find anything, it escalates: CloakBrowser (a stealth headless
Chromium, for Cloudflare challenges and JS single-page apps) and then Jina
Reader. Requests are sent with a full browser header set - several Berlin sites
answer a bare `User-Agent` with 403.

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