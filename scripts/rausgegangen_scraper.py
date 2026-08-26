#!/usr/bin/env python3
"""
Scraper for rausgegangen.de using Jina.ai Reader (Standardized)
"""

import argparse
import json
import os
import re
import sys
import logging
from pathlib import Path
from datetime import datetime, timedelta
import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True, help='URL to scrape')
    parser.add_argument('--output', required=True, help='Output JSON file')
    parser.add_argument('--price-max', type=float, default=15.0)
    parser.add_argument('--date-days', type=int, default=14)
    parser.add_argument('--save-html', action='store_true')
    parser.add_argument('--html-output', help='Path where fetched page content should be saved')
    return parser.parse_args()

def get_jina_content(url: str) -> str:
    jina_url = f"https://r.jina.ai/{url}"
    headers = {}
    if os.environ.get("JINA_API_KEY"):
        headers["Authorization"] = f"Bearer {os.environ.get('JINA_API_KEY')}"

    try:
        response = requests.get(jina_url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.text
    except Exception as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return ""

def extract_events_from_markdown(markdown: str, source_url: str) -> list:
    """Extract event cards from a Jina Reader snapshot.

    Rausgegangen renders card fields on separate Markdown lines, so looking
    for a time and price on the same line (the previous implementation) never
    found the cards. Event links are a stable card boundary; nearby text is
    then used for the optional time, price, and venue fields.
    """
    events = []
    lines = markdown.split('\n')
    seen = set()

    event_link = re.compile(
        r'\[([^\]]{3,200})\]\((https?://(?:www\.)?rausgegangen\.de/(?:en/)?events/[^)]+)\)',
        re.IGNORECASE,
    )
    for index, line in enumerate(lines):
        match = event_link.search(line)
        if not match:
            continue

        title = re.sub(r'^!?Image\s+\d+:\s*', '', match.group(1), flags=re.IGNORECASE)
        title = re.sub(r'[*_`]', '', title).strip(' -:')
        event_url = match.group(2)
        if len(title) < 3 or event_url in seen:
            continue

        # Card metadata can appear before or after its link in Jina output.
        card_text = ' '.join(lines[max(0, index - 4):index + 7])
        time_match = re.search(r'\b([01]?\d|2[0-3]):[0-5]\d\b', card_text)
        price_match = re.search(
            r'(?:from\s+)?(\d+(?:[,.]\d+)?)\s*(?:€|EUR)|\b(free|gratis|kostenlos)\b',
            card_text,
            re.IGNORECASE,
        )
        price = 0.0
        if price_match and price_match.group(1):
            price = float(price_match.group(1).replace(',', '.'))

        seen.add(event_url)
        events.append({
            'title': title,
            'date': datetime.now().strftime('%Y-%m-%d'),
            'time': time_match.group(0) if time_match else '',
            'price': price,
            'category': 'social',
            'description': title,
            'url': event_url,
            'venue': 'Berlin',
            'source_url': source_url
        })
    
    return events

def main():
    args = parse_args()
    
    logger.info(f"Fetching {args.url}...")
    markdown = get_jina_content(args.url)
    if not markdown.strip():
        logger.error("The fetched page was empty")
        return 1
    
    if args.save_html:
        html_output = args.html_output or f"data/html/{args.url.split('/')[-2] or 'rausgegangen'}.html"
        os.makedirs(os.path.dirname(html_output), exist_ok=True)
        with open(html_output, 'w') as f:
            f.write(markdown)
    
    events = extract_events_from_markdown(markdown, args.url)

    # Filter by price
    filtered_events = [e for e in events if e['price'] <= args.price_max]
    
    output = {
        "source": args.url,
        "scraped_at": datetime.now().isoformat(),
        "event_count": len(filtered_events),
        "events": filtered_events
    }
    
    with open(args.output, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print(f"Extracted {len(filtered_events)} events")
    return 0

if __name__ == '__main__':
    sys.exit(main())
