"""
Eventbrite Event Scraper

Scrapes events from Eventbrite using CloakBrowser for stealth navigation.
"""

import os
import sys
import json
import argparse
import logging
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any

import requests

try:
    from cloakbrowser import launch
    CLOAKBROWSER_AVAILABLE = True
except ImportError:
    CLOAKBROWSER_AVAILABLE = False
    print("Warning: CloakBrowser not installed. Install with: pip install cloakbrowser")

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def scrape_eventbrite(url: str, price_max: float = 15.0, date_range_days: int = 14) -> List[Dict[str, Any]]:
    """
    Scrape events from Eventbrite.
    """
    if not CLOAKBROWSER_AVAILABLE:
        logger.warning("CloakBrowser not available; using Jina Reader fallback")
        return scrape_eventbrite_with_jina(url, price_max)
    
    logger.info(f"Scraping Eventbrite: {url}")
    
    browser = None
    context = None
    
    try:
        # Launch CloakBrowser with stealth settings
        browser = launch(headless=True, humanize=True)
        context = browser.new_context()
        page = context.new_page()

        # Navigate to the URL
        logger.info(f"Navigating to {url}")
        page.goto(url, wait_until="networkidle", timeout=60000)

        # Wait for content to load
        page.wait_for_timeout(5000)

        # Extract events using specific Eventbrite selectors
        events = []

        # Eventbrite event selectors
        elements = page.query_selector_all('li.search-main-content__events-list-item, div.search-event-card-wrapper, div.discover-horizontal-event-card')

        if not elements or len(elements) == 0:
            logger.warning("No events found with primary selectors, trying fallback...")
            elements = page.query_selector_all('article, [data-testid="event-card"]')

        for i, element in enumerate(elements[:40]):
            try:
                # Title
                title_elem = element.query_selector('h3, h2, [class*="title"]')
                title_text = title_elem.inner_text().strip() if title_elem else f"Event {i+1}"

                # Date and time
                date_elem = element.query_selector('[class*="date"], [class*="time"], div.event-card-details__status')
                date_text = date_elem.inner_text().strip() if date_elem else ""

                # Price - Eventbrite often shows price in a specific badge or list item
                price_elem = element.query_selector('div.event-card__price, [class*="price"]')
                price_text = price_elem.inner_text().strip() if price_elem else "Free"

                # Parse price
                price = 0.0
                if "free" in price_text.lower() or "gratis" in price_text.lower():
                    price = 0.0
                else:
                    import re
                    price_match = re.search(r'(\d+[,.]\d+)', price_text)
                    if price_match:
                        price = float(price_match.group(1).replace(',', '.'))

                if price > price_max:
                    continue

                # Venue
                venue_elem = element.query_selector('[class*="venue"], [class*="location"]')
                venue_text = venue_elem.inner_text().strip() if venue_elem else "Berlin"

                # URL
                link_elem = element.query_selector('a.event-card-link, a')
                event_url = link_elem.get_attribute('href') if link_elem else url
                if event_url and not event_url.startswith('http'):
                    event_url = f"https://www.eventbrite.de{event_url}"

                # Description (usually truncated on list view)
                desc_text = f"Event at {venue_text} on {date_text}"

                # Create event object with standardized schema
                event = {
                    "title": title_text,
                    "date": datetime.now().strftime("%Y-%m-%d"), # Simplified parsing
                    "time": "",
                    "price": price,
                    "category": "social",
                    "description": desc_text,
                    "url": event_url,
                    "venue": venue_text,
                    "source_url": url
                }

                events.append(event)
                logger.info(f"Extracted: {title_text} - {price}€")

            except Exception as e:
                logger.debug(f"Error extracting event {i}: {e}")
                continue

        if events:
            return events

        logger.warning("CloakBrowser produced 0 Eventbrite events; using Jina Reader fallback")
        return scrape_eventbrite_with_jina(url, price_max)

    except Exception as e:
        logger.error(f"Error scraping Eventbrite with CloakBrowser: {e}")
        return scrape_eventbrite_with_jina(url, price_max)
    finally:
        if context: context.close()
        if browser: browser.close()


def fetch_jina_content(url: str) -> str:
    """Fetch a readable page snapshot via Jina Reader."""
    jina_url = f"https://r.jina.ai/{url}"
    headers = {}
    if os.environ.get("JINA_API_KEY"):
        headers["Authorization"] = f"Bearer {os.environ['JINA_API_KEY']}"
    response = requests.get(jina_url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.text


def parse_price(price_text: str) -> float:
    if "free" in price_text.lower() or "gratis" in price_text.lower():
        return 0.0
    price_match = re.search(r'(\d+[,.]\d+|\d+)\s*(?:€|EUR)', price_text, re.IGNORECASE)
    return float(price_match.group(1).replace(',', '.')) if price_match else 0.0


def scrape_eventbrite_with_jina(url: str, price_max: float = 15.0) -> List[Dict[str, Any]]:
    """Fallback parser for GitHub Actions when browser automation is blocked."""
    markdown = fetch_jina_content(url)
    events = []
    seen = set()

    for line in markdown.splitlines():
        text = line.strip()
        if not text or len(text) < 8:
            continue
        if not re.search(r'eventbrite|tickets?|free|gratis|€|berlin|\d{1,2}:\d{2}', text, re.IGNORECASE):
            continue

        link_match = re.search(r'\[([^\]]{5,160})\]\((https?://[^)]+)\)', text)
        title = link_match.group(1).strip() if link_match else re.sub(r'[#*_`>-]', '', text).strip()
        event_url = link_match.group(2) if link_match else url

        if len(title) < 5 or title.lower() in seen:
            continue

        price = parse_price(text)
        if price > price_max:
            continue

        seen.add(title.lower())
        events.append({
            "title": title[:180],
            "date": datetime.now().strftime("%Y-%m-%d"),
            "time": "",
            "price": price,
            "category": "social",
            "description": text[:500],
            "url": event_url,
            "venue": "Berlin",
            "source_url": url
        })

        if len(events) >= 40:
            break

    return events


def main():
    parser = argparse.ArgumentParser(description="Eventbrite Scraper")
    parser.add_argument("--url", default="https://www.eventbrite.de/d/germany/berlin/events/", help="URL to scrape")
    parser.add_argument("--output", required=True, help="Output JSON file")
    parser.add_argument("--price-max", type=float, default=15.0, help="Max price")
    parser.add_argument("--date-days", type=int, default=14, help="Date range")
    parser.add_argument("--save-html", action="store_true", help="Save HTML")
    parser.add_argument("--html-output", help="Path where fetched page content should be saved")

    args = parser.parse_args()
    
    try:
        events = scrape_eventbrite(args.url, args.price_max, args.date_days)
        if args.save_html:
            html_output = args.html_output or "data/html/eventbrite.html"
            os.makedirs(os.path.dirname(html_output), exist_ok=True)
            try:
                with open(html_output, "w") as f:
                    f.write(fetch_jina_content(args.url))
            except Exception as e:
                logger.warning(f"Could not save Eventbrite HTML snapshot: {e}")
        
        output = {
            "source": args.url,
            "scraped_at": datetime.now().isoformat(),
            "event_count": len(events),
            "events": events
        }

        with open(args.output, "w") as f:
            json.dump(output, f, indent=2)
        
        print(f"✓ Scraped {len(events)} events to {args.output}")
        
    except Exception as e:
        logger.error(f"Scraping failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
