#!/usr/bin/env python3
"""
Scraper for rausgegangen.de using Jina.ai Reader
Usage: python rausgegangen_scraper.py --start-date 2026-07-06 --end-date 2026-07-12
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime, timedelta
import requests

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start-date', required=True, help='Start date YYYY-MM-DD')
    parser.add_argument('--end-date', required=True, help='End date YYYY-MM-DD')
    parser.add_argument('--output', default='/tmp/events_raw.json')
    return parser.parse_args()

def get_jina_content(url: str) -> str:
    """Fetch content using Jina.ai Reader"""
    # Load API key from environment or .env file
    if 'JINA_API_KEY' not in os.environ:
        env_path = Path.home() / '.env'
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    if line.startswith('JINA_API_KEY='):
                        os.environ['JINA_API_KEY'] = line.strip().split('=', 1)[1]
                        break
    
    api_key = os.getenv('JINA_API_KEY')
    if not api_key:
        logger.error("JINA_API_KEY not set")
        return ""
    
    jina_url = f"https://r.jina.ai/{url}"
    headers = {"Authorization": f"Bearer {api_key}"}
    
    try:
        response = requests.get(jina_url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.text
    except Exception as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return ""

def extract_events_from_markdown(markdown: str, start_date: str, end_date: str) -> list:
    """Extract events from Jina.ai markdown output"""
    events = []
    
    # Parse date range
    start = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')
    
    lines = markdown.split('\n')
    
    for line in lines:
        # Look for event lines with date, time, and price
        # Pattern: ![Image X: TITLE](url) NUMBER Date | TIME Location Price Category
        if re.search(r'\d{1,2}:\d{2}.*?(?:Free|€|\d+[,.]\d+\s*€)', line):
            # Extract components
            time_match = re.search(r'(\d{1,2}:\d{2})', line)
            date_match = re.search(r'(Today|Tomorrow|Fr,|Sa,|So,|\d{1,2}\.\s*\w+)', line)
            price_match = re.search(r'(Free admission|\d+[,.]\d+\s*€|\d+[,.]\d+\s*to\s*\d+[,.]\d+\s*€|from\s+\d+[,.]\d+\s*€|0,00\s*to\s+\d+[,.]\d+\s*€|keine Preisangabe)', line, re.IGNORECASE)
            
            if time_match and price_match:
                # Extract title
                title_match = re.search(r'!\[Image \d+:\s*(.*?)\]\([^)]+\)', line)
                if title_match:
                    title = title_match.group(1).strip()
                else:
                    continue
                
                # Extract location
                time_end = time_match.end()
                price_start = price_match.start()
                location = line[time_end:price_start].strip()
                location = re.sub(r'\|.*$', '', location).strip()
                
                # Parse price
                price = None
                price_str = price_match.group(1)
                if 'Free' in price_str or 'free' in price_str.lower():
                    price = 0.0
                elif 'keine Preisangabe' in price_str:
                    price = None  # Unknown
                else:
                    prices = re.findall(r'(\d+[,.]\d+)', price_str)
                    if prices:
                        price = float(prices[0].replace(',', '.'))
                
                # Parse date (simplified - would need more logic for actual dates)
                event_date = start_date  # Default to start date
                if 'Today' in line:
                    event_date = datetime.now().strftime('%Y-%m-%d')
                elif 'Tomorrow' in line:
                    tomorrow = datetime.now() + timedelta(days=1)
                    event_date = tomorrow.strftime('%Y-%m-%d')
                elif date_match:
                    # Parse German date format
                    date_text = date_match.group(1)
                    # Simplified - would need proper date parsing
                    event_date = start_date
                
                # Filter by date range
                try:
                    event_dt = datetime.strptime(event_date, '%Y-%m-%d')
                    if not (start <= event_dt <= end):
                        continue
                except:
                    continue
                
                events.append({
                    'title': title,
                    'date': event_date,
                    'time': time_match.group(1),
                    'price': price,
                    'location': location,
                    'description': '',
                    'source_url': 'https://rausgegangen.de/en/berlin/'
                })
    
    return events

def main():
    args = parse_args()
    
    # URLs to scrape (multiple date pages)
    urls = [
        "http://rausgegangen.de/en/berlin/tipps-fuer-heute/",
        "http://rausgegangen.de/en/berlin/tips-for-tomorrow/",
        "http://rausgegangen.de/en/berlin/tips-for-the-weekend/",
    ]
    
    all_events = []
    
    for url in urls:
        logger.info(f"Fetching {url}...")
        markdown = get_jina_content(url)
        
        if not markdown:
            continue
        
        events = extract_events_from_markdown(markdown, args.start_date, args.end_date)
        all_events.extend(events)
        logger.info(f"Extracted {len(events)} events from {url}")
    
    # Remove duplicates
    seen = set()
    unique_events = []
    for event in all_events:
        key = (event['title'].lower(), event['date'], event['time'])
        if key not in seen:
            seen.add(key)
            unique_events.append(event)
    
    # Save output
    with open(args.output, 'w') as f:
        json.dump(unique_events, f, indent=2, ensure_ascii=False)
    
    print(f"Extracted {len(unique_events)} unique events")
    return 0 if unique_events else 1

if __name__ == '__main__':
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    sys.exit(main())
