# Event Scraper - Quick Start Guide

## Setup (5 minutes)

### 1. Install Dependencies
```bash
pip install -r requirements.txt
pip install cloakbrowser  # For stealth scraping
```

### 2. Configure Environment
Your `.env` file should contain your Jules API key:
```bash
JULES_API_KEY=your_jules_api_key_here
```
Copy `.env.example` to `.env` and add your key.

### 3. Test Jules API Connection
```bash
python scripts/jules_client.py list-sources
```

Expected output: A list of GitHub repositories connected to your Jules account.

## Usage

### Option 1: Direct Scraper (No Jules)
```bash
python scripts/jules_cloak_scraper.py \
  --url "https://rausgegangen.de/en/berlin/tipps-fuer-heute/" \
  --site-name "Rausgegangen Berlin" \
  --output events.json
```

### Option 2: With Jules-Generated Scraper
```bash
python scripts/jules_cloak_scraper.py \
  --url "https://example-events.com" \
  --site-name "Example Events" \
  --use-jules-scraper \
  --output events.json
```

### Options
- `--url`: Target URL to scrape
- `--site-name`: Human-readable site name
- `--agent-id`: Jules agent to use (default: jules-1)
- `--price-max`: Maximum event price (default: 15.0)
- `--date-days`: Date range in days (default: 14)
- `--output`: Output JSON file
- `--use-jules-scraper`: Generate scraper with Jules AI

## GitHub Actions Deployment

### 1. Push to GitHub
```bash
git add .
git commit -m "Add Jules API integration"
git push origin main
```

### 2. Configure Repository Secrets
Go to Settings > Secrets and add:
- `JULES_API_KEY`: Your Jules API key
- `GITHUB_TOKEN`: Auto-provided by GitHub

### 3. Enable GitHub Pages
Settings > Pages > Source: main branch /docs folder

## Testing Locally

```bash
# Test Jules client
python scripts/jules_client.py list-sources

# Test scraper with CloakBrowser
python scripts/jules_cloak_scraper.py \
  --url "https://rausgegangen.de/en/berlin/tipps-fuer-heute/" \
  --site-name "Test" \
  --output test_events.json

# View results
cat test_events.json
```

## Troubleshooting

### Jules API Key Not Found
```bash
# Check .env file exists
ls -la .env

# Verify key is set
grep JULES_API_KEY .env
```

### CloakBrowser Not Installed
```bash
pip install cloakbrowser
python -m cloakbrowser info  # Check installation
```

### Proxy Required for Anti-Bot Sites
Add to `.env`:
```bash
CLOAKBROWSER_PROXY=http://residential-proxy:port
```

## Architecture

```
Jules API (AI coding) → Generates scraper logic
       ↓
CloakBrowser (stealth) → Navigates target sites
       ↓
Event Extraction → Parses HTML for events
       ↓
Filter (≤15€) → Price and date filtering
       ↓
JSON Output → GitHub Pages display
```

## Next Steps

1. ✅ Test local scraping
2. ⏳ Deploy to GitHub Actions
3. ⏳ Configure GitHub Pages
4. ⏳ Add more event sources (Eventbrite, etc.)
