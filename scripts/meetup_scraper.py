"""
Meetup.com Event Scraper

Scrapes events from Meetup.com using CloakBrowser for stealth navigation.
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


def scrape_meetup(url: str, price_max: float = 15.0, date_range_days: int = 14) -> List[Dict[str, Any]]:
    """
    Scrape events from Meetup.com.
    
    Args:
        url: Meetup.com URL to scrape
        price_max: Maximum price to include
        date_range_days: How many days ahead to look
    
    Returns:
        List of extracted events
    """
    if not CLOAKBROWSER_AVAILABLE:
        logger.warning("CloakBrowser not available; using Jina Reader fallback")
        return scrape_meetup_with_jina(url, price_max)
    
    logger.info(f"Scraping Meetup: {url}")
    
    browser = None
    context = None
    
    try:
        # Launch CloakBrowser
        browser = launch(headless=True, humanize=True)
        context = browser.new_context()
        page = context.new_page()
        
        # Navigate to the URL
        logger.info(f"Navigating to {url}")
        page.goto(url, wait_until="networkidle", timeout=60000)
        
        # Wait for content to load
        page.wait_for_timeout(3000)
        
        # Extract events using Playwright
        events = []
        
        # Meetup.com event selectors (may need adjustment based on current site structure)
        event_selectors = [
            'div[data-testid="event-card"]',
            'article.event-card',
            'div.event-card',
            '[class*="eventCard"]',
            '[class*="EventCard"]',
        ]
        
        for selector in event_selectors:
            try:
                elements = page.query_selector_all(selector)
                if elements:
                    logger.info(f"Found {len(elements)} events with selector: {selector}")
                    break
            except:
                continue
        
        # If no specific selectors found, try to extract any event-like elements
        if not elements or len(elements) == 0:
            # Fallback: look for any elements with event-related attributes
            elements = page.query_selector_all('[class*="event"], [data-testid*="event"]')
        
        for i, element in enumerate(elements[:50]):  # Limit to 50 events
            try:
                # Extract event data
                title = element.query_selector('h3, h4, [class*="title"]')
                title_text = title.inner_text().strip() if title else f"Event {i+1}"
                
                # Date and time
                date_elem = element.query_selector('[class*="date"], [class*="time"], time')
                date_text = date_elem.inner_text().strip() if date_elem else ""
                
                # Price
                price_elem = element.query_selector('[class*="price"], [class*="cost"]')
                price_text = price_elem.inner_text().strip() if price_elem else "Free"
                
                # Parse price
                price = 0
                if "free" in price_text.lower() or "gratis" in price_text.lower():
                    price = 0
                else:
                    import re
                    price_match = re.search(r'[\$€£](\d+\.?\d*)', price_text)
                    if price_match:
                        price = float(price_match.group(1))
                
                # Skip if over price limit
                if price > price_max:
                    continue
                
                # Venue
                venue_elem = element.query_selector('[class*="venue"], [class*="location"]')
                venue_text = venue_elem.inner_text().strip() if venue_elem else "Online"
                
                # Description
                desc_elem = element.query_selector('[class*="description"], [class*="summary"]')
                desc_text = desc_elem.inner_text().strip() if desc_elem else ""
                
                # URL
                link_elem = element.query_selector('a')
                event_url = link_elem.get_attribute('href') if link_elem else url
                
                # Create event object
                event = {
                    "title": title_text,
                    "date": parse_meetup_date(date_text),
                    "time": extract_time(date_text),
                    "price": price,
                    "category": "social",  # Default category
                    "description": desc_text[:500] if desc_text else "",
                    "url": event_url if event_url.startswith('http') else f"https://meetup.com{event_url}",
                    "venue": venue_text,
                    "source_url": url
                }
                
                events.append(event)
                logger.info(f"Extracted event: {title_text} - €{price}")
                
            except Exception as e:
                logger.warning(f"Error extracting event {i}: {e}")
                continue
        
        logger.info(f"Successfully extracted {len(events)} events from Meetup")
        if events:
            return events

        logger.warning("CloakBrowser produced 0 Meetup events; using Jina Reader fallback")
        return scrape_meetup_with_jina(url, price_max)
        
    except Exception as e:
        logger.error(f"Error scraping Meetup with CloakBrowser: {e}")
        return scrape_meetup_with_jina(url, price_max)
    finally:
        if context:
            context.close()
        if browser:
            browser.close()


def fetch_jina_content(url: str) -> str:
    """Fetch a readable page snapshot via Jina Reader."""
    jina_url = f"https://r.jina.ai/{url}"
    headers = {}
    if os.environ.get("JINA_API_KEY"):
        headers["Authorization"] = f"Bearer {os.environ['JINA_API_KEY']}"
    response = requests.get(jina_url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.text


def scrape_meetup_with_jina(url: str, price_max: float = 15.0) -> List[Dict[str, Any]]:
    """Fallback parser for GitHub Actions when browser automation is blocked."""
    markdown = fetch_jina_content(url)
    events = []
    seen = set()

    for line in markdown.splitlines():
        text = line.strip()
        if not text or len(text) < 8:
            continue
        if not re.search(r'meetup|rsvp|online|free|gratis|€|berlin|\d{1,2}:\d{2}', text, re.IGNORECASE):
            continue

        link_match = re.search(r'\[([^\]]{5,160})\]\((https?://[^)]+)\)', text)
        title = link_match.group(1).strip() if link_match else re.sub(r'[#*_`>-]', '', text).strip()
        event_url = link_match.group(2) if link_match else url

        if len(title) < 5 or title.lower() in seen:
            continue

        price = 0.0
        price_match = re.search(r'(\d+[,.]\d+|\d+)\s*(?:€|EUR)', text, re.IGNORECASE)
        if price_match:
            price = float(price_match.group(1).replace(',', '.'))
        if price > price_max:
            continue

        seen.add(title.lower())
        events.append({
            "title": title[:180],
            "date": parse_meetup_date(text),
            "time": extract_time(text),
            "price": price,
            "category": "social",
            "description": text[:500],
            "url": event_url,
            "venue": "Berlin",
            "source_url": url
        })

        if len(events) >= 50:
            break

    return events


def parse_meetup_date(date_text: str) -> str:
    """Parse Meetup date text to YYYY-MM-DD format"""
    from datetime import datetime, timedelta
    
    # Try common date formats
    formats = [
        "%b %d, %Y",  # Jan 15, 2024
        "%B %d, %Y",  # January 15, 2024
        "%d %b %Y",   # 15 Jan 2024
        "%Y-%m-%d",   # 2024-01-15
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(date_text, fmt)
            return dt.strftime("%Y-%m-%d")
        except:
            continue
    
    # If parsing fails, return today's date as fallback
    return datetime.now().strftime("%Y-%m-%d")


def extract_time(date_text: str) -> str:
    """Extract time from date text"""
    import re
    
    # Look for time patterns
    time_match = re.search(r'(\d{1,2}:\d{2})\s*(AM|PM|am|pm)?', date_text, re.IGNORECASE)
    if time_match:
        time_str = time_match.group(1)
        period = time_match.group(2) or ""
        return f"{time_str} {period}".strip()
    
    return ""


def main():
    parser = argparse.ArgumentParser(description="Meetup.com Event Scraper")
    parser.add_argument("--url", required=True, help="Meetup.com URL to scrape")
    parser.add_argument("--output", required=True, help="Output JSON file")
    parser.add_argument("--price-max", type=float, default=15.0, help="Maximum event price")
    parser.add_argument("--date-days", type=int, default=14, help="Date range in days")
    parser.add_argument("--save-html", action="store_true", help="Save HTML for analysis")
    parser.add_argument("--html-output", help="Path where fetched page content should be saved")
    
    args = parser.parse_args()
    
    # Scrape events
    try:
        events = scrape_meetup(
            url=args.url,
            price_max=args.price_max,
            date_range_days=args.date_days
        )
        
        # Create output
        output = {
            "source": args.url,
            "scraped_at": datetime.now().isoformat(),
            "event_count": len(events),
            "events": events
        }
        
        # Save to file
        with open(args.output, "w") as f:
            json.dump(output, f, indent=2)
        
        print(f"✓ Scraped {len(events)} events to {args.output}")
        
        # Save HTML if requested
        if args.save_html:
            html_output = args.html_output or "data/html/meetup.html"
            os.makedirs(os.path.dirname(html_output), exist_ok=True)
            try:
                with open(html_output, "w") as f:
                    f.write(fetch_jina_content(args.url))
            except Exception as e:
                logger.warning(f"Could not save Meetup HTML snapshot: {e}")
        
    except Exception as e:
        logger.error(f"Scraping failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
