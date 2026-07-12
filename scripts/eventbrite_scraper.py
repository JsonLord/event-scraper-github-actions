"""
Eventbrite Event Scraper

Scrapes events from Eventbrite using CloakBrowser for stealth navigation.
"""

import os
import sys
import json
import argparse
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any

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
        raise RuntimeError("CloakBrowser not available")
    
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

        return events

    except Exception as e:
        logger.error(f"Error scraping Eventbrite: {e}")
        raise
    finally:
        if context: context.close()
        if browser: browser.close()


def main():
    parser = argparse.ArgumentParser(description="Eventbrite Scraper")
    parser.add_argument("--url", default="https://www.eventbrite.de/d/germany/berlin/events/", help="URL to scrape")
    parser.add_argument("--output", required=True, help="Output JSON file")
    parser.add_argument("--price-max", type=float, default=15.0, help="Max price")
    parser.add_argument("--date-days", type=int, default=14, help="Date range")
    parser.add_argument("--save-html", action="store_true", help="Save HTML")

    args = parser.parse_args()
    
    try:
        events = scrape_eventbrite(args.url, args.price_max, args.date_days)
        
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
