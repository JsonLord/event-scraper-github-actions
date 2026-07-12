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
    events = []
    lines = markdown.split('\n')
    
    for line in lines:
        if re.search(r'\d{1,2}:\d{2}.*?(?:Free|€|\d+[,.]\d+\s*€)', line):
            time_match = re.search(r'(\d{1,2}:\d{2})', line)
            price_match = re.search(r'(Free admission|\d+[,.]\d+\s*€|from\s+\d+[,.]\d+\s*€|0,00\s*to\s+\d+[,.]\d+\s*€)', line, re.IGNORECASE)
            
            if time_match and price_match:
                title_match = re.search(r'!\[Image \d+:\s*(.*?)\]\([^)]+\)', line)
                title = title_match.group(1).strip() if title_match else "Unknown Event"
                
                price = 0.0
                price_str = price_match.group(1)
                if 'Free' in price_str or 'free' in price_str.lower():
                    price = 0.0
                else:
                    prices = re.findall(r'(\d+[,.]\d+)', price_str)
                    if prices:
                        price = float(prices[0].replace(',', '.'))
                
                events.append({
                    'title': title,
                    'date': datetime.now().strftime('%Y-%m-%d'),
                    'time': time_match.group(1),
                    'price': price,
                    'category': 'music', # Default for Rausgegangen usually
                    'description': '',
                    'url': source_url,
                    'venue': 'Various',
                    'source_url': source_url
                })
    
    return events

def main():
    args = parse_args()
    
    logger.info(f"Fetching {args.url}...")
    markdown = get_jina_content(args.url)
    
    if args.save_html:
        os.makedirs("data/html", exist_ok=True)
        site_name = args.url.split('/')[-2] or "rausgegangen"
        with open(f"data/html/{site_name}.html", 'w') as f:
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
