# Weekly Multi-Source Event Scraper Configuration

## Overview
This workflow scrapes multiple event sources in parallel every Sunday at 5 PM UTC.
Each source runs in its own Jules session with CloakBrowser for stealth scraping.

## Configuration

### Default URLs (Edit to add/remove sources)
Edit the workflow file `.github/workflows/weekly-multi-source.yml` and modify:

```yaml
urls="https://rausgegangen.de/en/berlin/tipps-fuer-heute/
https://www.eventbrite.de/d/germany/berlin/events/
https://www.meetup.com/berlin/events/"
```

### Manual Override
You can trigger a manual run with custom URLs:
1. Go to Actions → Weekly Multi-Source Event Scraper
2. Click "Run workflow"
3. Enter comma-separated URLs in the "urls" field

## Workflow Steps

### 1. Load Configuration
- Reads URLs from config or manual input
- Prepares matrix for parallel execution

### 2. Scrape All Sources (Parallel)
- Each URL runs in its own job (parallel execution)
- Uses CloakBrowser for stealth navigation
- Jules AI generates/optimizes scraper logic per source
- Results saved as separate artifacts: `events_{sourcename}.json`

### 3. Aggregate Results
- Combines all events into single `events.json`
- Tracks event counts per source
- Prepares data for GitHub Pages

### 4. Check Completeness
- Validates each source had successful scrape
- Identifies sources with 0 events (needs improvement)
- Generates completeness report

### 5. Auto-Improve Scrapers (Conditional)
- For sources that failed/returned empty:
  - Runs Jules AI analysis
  - Generates improved scraper code
  - Creates GitHub PR with improvements
  - Label: `auto-improvement`, `jules-ai`

### 6. Deploy to GitHub Pages
- Updates `docs/events.json`
- Site available at: `https://username.github.io/repo/`

## Timing

**Every Sunday 5 PM UTC:**
- 17:00 - All sources start scraping (parallel)
- 17:00-18:30 - Scraping phase (90 min max per source)
- 18:30 - Aggregation
- 18:35 - Completeness check
- 18:40 - Improvement PRs created (if needed)
- 18:45 - GitHub Pages deployed

## Event Schema

Each event object contains:
```json
{
  "title": "Event title",
  "date": "2024-01-15",
  "time": "19:00",
  "price": 12.50,
  "category": "music",
  "description": "Event description",
  "url": "https://...",
  "venue": "Venue name",
  "source_url": "https://original-source.com"
}
```

## Filtering
- **Price**: Events ≤ 15€ only
- **Date Range**: Next 14 days only
- **Categories**: music, dance, social, networking

## Troubleshooting

### Source Returns 0 Events
- Check the completeness report artifact
- Review the auto-created improvement PR
- Manually inspect the source URL for changes

### Scraping Timeout
- Increase `timeout-minutes` in workflow (default: 120)
- Check if site has new anti-bot measures
- Consider adding residential proxy

### Jules Session Fails
- Verify JULES_API_KEY secret is set
- Check Jules dashboard for session status
- Review workflow logs for error details
