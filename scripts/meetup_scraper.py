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
from datetime import datetime
from typing import List, Dict, Any, Optional

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from event_utils import (  # noqa: E402
    clean_text,
    clean_url,
    dedupe_events,
    normalize_venue,
    parse_date,
    parse_price,
    parse_time,
    scrape_window,
    validate_events,
)

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
                # A card with no readable name is page furniture, not an
                # event. Naming it "Event {i+1}" and defaulting its venue to
                # "Online" and its price to 0 put a dozen contentless rows at
                # the very top of the published table, because a price of 0
                # scored better than any real event's unknown price.
                title = element.query_selector('h3, h4, [class*="title"]')
                title_text = clean_text(title.inner_text()) if title else ""
                if not title_text:
                    continue

                date_elem = element.query_selector('[class*="date"], [class*="time"], time')
                date_text = date_elem.inner_text().strip() if date_elem else ""

                price_elem = element.query_selector('[class*="price"], [class*="cost"]')
                price = parse_price(price_elem.inner_text()) if price_elem else None
                if price is not None and price > price_max:
                    continue

                venue_elem = element.query_selector('[class*="venue"], [class*="location"]')
                venue_text = normalize_venue(venue_elem.inner_text()) if venue_elem else ""

                desc_elem = element.query_selector('[class*="description"], [class*="summary"]')
                desc_text = clean_text(desc_elem.inner_text(), max_length=400) if desc_elem else ""

                link_elem = element.query_selector('a')
                event_url = link_elem.get_attribute('href') if link_elem else ""
                if event_url and not event_url.startswith("http"):
                    event_url = f"https://www.meetup.com{event_url}"

                events.append({
                    "title": title_text,
                    "date": parse_meetup_date(date_text) or "",
                    "time": parse_time(date_text),
                    "price": price,
                    "category": "",
                    "description": desc_text,
                    "url": clean_url(event_url or url),
                    "venue": venue_text,
                    "source_url": url,
                })
                logger.info(f"Extracted event: {title_text}")

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

        price = parse_price(text)
        if price is not None and price > price_max:
            continue

        seen.add(title.lower())
        events.append({
            "title": clean_text(title, max_length=180),
            "date": parse_meetup_date(text) or "",
            "time": parse_time(text),
            "price": price,
            "category": "",
            "description": clean_text(text, max_length=400),
            "url": clean_url(event_url),
            # "Berlin" as a blanket venue was how San Francisco meetups
            # acquired a Berlin address in the published table.
            "venue": "",
            "source_url": url,
        })

        if len(events) >= 50:
            break

    return events


def parse_meetup_date(date_text: str) -> Optional[str]:
    """Parse Meetup date text to ISO YYYY-MM-DD, or None when absent.

    Falling back to today turned every card whose date selector missed into a
    confident-looking event happening now.
    """
    if not date_text:
        return None
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_text.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return parse_date(date_text)


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
    parser.add_argument("--date-days", type=int, default=7,
                        help="Only keep events starting within this many days from today")
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

        # Meetup is a global platform whose "popular events nearby" module
        # geolocates the caller, so a Berlin query answered from a US-hosted
        # runner returns San Francisco. require_berlin_signal drops anything
        # with no independent tie to Berlin.
        window_start, window_end = scrape_window(args.date_days)
        kept, rejected = validate_events(
            events,
            source_url=args.url,
            window_start=window_start,
            window_end=window_end,
            max_price=args.price_max,
            require_berlin_signal=True,
        )
        events = dedupe_events(kept)
        logger.info(
            f"{len(events)} Berlin events kept for {window_start}..{window_end} "
            f"({rejected} rejected as unusable, out of window or not in Berlin)"
        )

        output = {
            "source": args.url,
            "scraped_at": datetime.now().isoformat(),
            "event_count": len(events),
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "events": events
        }
        
        # Save to file
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        
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
