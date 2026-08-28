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
from datetime import datetime
from typing import List, Dict, Any

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from event_utils import (  # noqa: E402
    clean_text,
    clean_url,
    dedupe_events,
    looks_synthetic_title,
    normalize_venue,
    parse_date,
    parse_price as parse_price_or_none,
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
                title_text = clean_text(title_elem.inner_text()) if title_elem else ""
                if not title_text:
                    continue

                # Date and time
                date_elem = element.query_selector('[class*="date"], [class*="time"], div.event-card-details__status')
                date_text = date_elem.inner_text().strip() if date_elem else ""

                # Price - Eventbrite often shows price in a specific badge or list item
                price_elem = element.query_selector('div.event-card__price, [class*="price"]')
                price = parse_price_or_none(price_elem.inner_text()) if price_elem else None
                if price is not None and price > price_max:
                    continue

                venue_elem = element.query_selector('[class*="venue"], [class*="location"]')
                venue_text = normalize_venue(venue_elem.inner_text()) if venue_elem else ""

                link_elem = element.query_selector('a.event-card-link, a')
                event_url = link_elem.get_attribute('href') if link_elem else ""
                if event_url and not event_url.startswith('http'):
                    event_url = f"https://www.eventbrite.de{event_url}"

                # Standardised schema; anything the card did not state stays
                # empty rather than being filled with a plausible guess.
                event = {
                    "title": title_text,
                    "date": parse_date(date_text) or "",
                    "time": parse_time(date_text),
                    "price": price,
                    "category": "",
                    "description": "",
                    "url": clean_url(event_url or url),
                    "venue": venue_text,
                    "source_url": url,
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


def clean_event_title(title: str) -> str:
    """Remove Jina's image labels from an Eventbrite event title."""
    title = re.sub(r'^!?\s*Image\s+\d+\s*:\s*', '', title, flags=re.IGNORECASE)
    title = re.sub(
        r'^(?:Hauptbild\s+f(?:ü|u)r|main\s+image(?:\s+for)?|event\s+image(?:\s+for)?)\s*',
        '',
        title,
        flags=re.IGNORECASE,
    )
    return re.sub(r'\s+', ' ', re.sub(r'[*_`\[\]]', '', title)).strip(' -:|\t')


def extract_markdown_event(text: str, fallback_url: str) -> tuple[str, str]:
    """Extract a clean title and destination from a Jina markdown line.

    Eventbrite cards are commonly represented as a linked image.  In that
    form the first Markdown URL is the CDN image, while the outer URL is the
    useful event destination.
    """
    linked_image = re.search(
        r'\[!\[([^\]]+)\]\(https?://[^)]+\)\]\((https?://[^)]+)\)', text
    )
    if linked_image:
        return clean_event_title(linked_image.group(1)), linked_image.group(2)

    links = re.findall(r'\[([^\]]{5,200})\]\((https?://[^)]+)\)', text)
    for label, destination in links:
        if 'eventbrite.' in destination.lower() and '/e/' in destination.lower():
            return clean_event_title(label), destination

    if links:
        label, destination = links[0]
        return clean_event_title(label), destination

    plain_text = re.sub(r'!\[[^\]]*\]\(https?://[^)]+\)', '', text)
    return clean_event_title(re.sub(r'[#*>-]', '', plain_text)), fallback_url


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

        title, event_url = extract_markdown_event(text, url)

        # Jina prefixes its output with "URL Source: <url>"; that header line
        # matched the keyword filter and shipped as two published "events".
        if len(title) < 5 or title.lower() in seen or looks_synthetic_title(title):
            continue

        price = parse_price_or_none(text)
        if price is not None and price > price_max:
            continue

        seen.add(title.lower())
        events.append({
            "title": clean_text(title, max_length=180),
            # Stamping every row with today's date and a "social" category
            # gave junk rows a full price and category score.
            "date": parse_date(text) or "",
            "time": parse_time(text),
            "price": price,
            "category": "",
            "description": clean_text(text, max_length=400),
            "url": clean_url(event_url),
            "venue": "",
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
    parser.add_argument("--date-days", type=int, default=7,
                        help="Only keep events starting within this many days from today")
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
        
        # Eventbrite is a global platform: scope results to Berlin and to the
        # target week before publishing anything.
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

        with open(args.output, "w") as f:
            json.dump(output, f, indent=2)
        
        print(f"✓ Scraped {len(events)} events to {args.output}")
        
    except Exception as e:
        logger.error(f"Scraping failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
