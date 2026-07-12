# Event Scraper System

A GitHub-powered event scraping system that replaces the original Heron-based implementation with GitHub Actions workflows and GitHub Pages for displaying results.

## Overview

This system scrapes event listings from various Berlin websites, filters for affordable events (≤15€), and provides a weekly overview. It has been adapted to run on GitHub Actions instead of the original Heron cron system.

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
  price_filter: 15.0
  date_range_days: 14
```

## Data Flow

1. **Scraping Phase**: Individual scrapers (rausgegangen_scraper.py, etc.) extract events from websites
2. **Filtering & Storage**: Events are filtered (price ≤15€) and stored in events.db
3. **Validation Phase**: Desk Agent 2.0 (placeholder) validates scrapes and finds missed events
4. **Improvement Phase**: Scraper scripts are automatically updated based on validation results
5. **Presentation**: Events are exported to JSON and displayed via GitHub Pages

## Customization

### Adding New Scrapers
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