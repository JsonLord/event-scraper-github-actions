# GitHub Actions Implementation Plan for Event Scraper

## Overview
This document describes the implementation of a GitHub Actions-based workflow system to replace the original Heron cron-based event scraper system.

## Key Components Created

### 1. GitHub Actions Workflows (`.github/workflows/`)

**weekly-scraper.yml**
- Schedule: Monday-Friday at 5:00 PM UTC (matches original cron: `0 17 * * 0-4`)
- Actions:
  - Runs `weekly-event-scraper.py`
  - Generates events.json for GitHub Pages
  - Deploys site to GitHub Pages
  - Uploads logs as artifacts

**validation.yml** 
- Schedule: Daily at 5:00 PM UTC (matches original cron: `0 17 * * *`)
- Actions:
  - Runs `firecrawl_validation.py` (modified for Desk Agent 2.0)
  - Saves validation reports
  - Updates GitHub Pages with validation summary

**improvement-cycle.yml**
- Schedule: Sunday at 6:00 PM UTC (matches original cron: `0 18 * * 0`)
- Actions:
  - Runs `scraper_improvement_cycle.py`
  - Automatically commits improved scraper scripts
  - Generates improvement reports

### 2. Modified Scripts (`scripts/`)

**firecrawl_validation.py**
- Replaced Firecrawl API calls with Desk Agent 2.0 placeholder
- Maintains same interface and functionality
- Includes configuration via environment variables:
  - `DESK_AGENT_HOST` (default: localhost)
  - `DESK_AGENT_PORT` (default: 7860)
  - `DESK_AGENT_ENABLED` (default: false for safe testing)
- Falls back to mock responses when disabled for safe testing

### 3. Supporting Files

**generate_github_pages.sh**
- Bash script to create GitHub Pages content
- Exports events from SQLite to JSON
- Creates responsive HTML interface with filtering
- Copies validation reports to docs/validation/

**requirements.txt**
- Lists Python dependencies: requests, PyYAML

**README.md**
- Comprehensive documentation of the system
- Architecture overview
- Setup instructions
- Customization guidelines

### 4. Placeholder Scrapers
- `eventbrite_scraper.py`: Stub implementation for Eventbrite scraping
- All original scrapers preserved (rausgegangen_scraper.py, etc.)

## How It Works

### Data Flow
1. **Scraping Phase**: Individual scrapers extract events from websites
2. **Storage**: Events filtered (price ≤15€) stored in events.db
3. **Validation**: Desk Agent 2.0 validates scrapes and finds missed opportunities
4. **Improvement**: Scraper scripts auto-updated based on validation results
5. **Presentation**: Events exported to JSON and displayed via GitHub Pages

### Environment Configuration
For production use with actual Desk Agent 2.0 instance:
```yaml
# In GitHub repository secrets
DESK_AGENT_HOST: your-desks-agent-host.com
DESK_AGENT_PORT: 443
DESK_AGENT_ENABLED: "true"
# DESK_AGENT_API_KEY: your-api-key-here  # if authentication required
```

## Deployment Instructions

1. Fork/create repository with this structure
2. Enable GitHub Pages (Settings → Pages → Source: main branch /docs)
3. Ensure GitHub Actions are enabled
4. Workflows will run automatically on their schedules
5. Site available at: `https://username.github.io/repository-name/`

## Customization

### Adding New Sources
1. Create scraper script in `scripts/` following existing patterns
2. Add entry to `config.yaml` under `urls`
3. Ensure scraper accepts `--start-date` `--end-date` `--output` args
4. Output JSON with standard event schema

### Modifying Validation
Edit `scripts/firecrawl_validation.py`:
- Adjust `call_desk_agent()` for actual Desk Agent 2.0 API
- Update `extract_events_from_desk_agent()` for response format
- Modify validation logic in `validate_and_retrieve_missed()` if needed

## Safety Features
- Desk Agent 2.0 defaults to disabled mode (returns empty results)
- Fail-safe mechanisms in all workflows
- Artifact preservation for debugging
- Informative logging throughout

## Maintenance
- Monitor Actions tab for workflow runs
- Review validation reports in docs/validation/
- Check GitHub Pages site for display issues
- Update scrapers as target websites change
- Enable Desk Agent 2.0 when moving from testing to production