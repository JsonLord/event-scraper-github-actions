#!/usr/bin/env python3
"""
Weekly Event Scraper - Main Orchestration Script
Runs every Sunday at 4 PM via cron job
"""

import os
import sys
import json
import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional
import subprocess
import yaml

# Configuration
CONFIG_PATH = Path.home() / 'event-scraper' / 'config.yaml'
DB_PATH = Path.home() / 'event-scraper' / 'events.db'
LOGS_DIR = Path.home() / 'event-scraper' / 'logs'
SCRIPTS_DIR = Path.home() / '.hermes' / 'scripts'

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOGS_DIR / f'scraper_{datetime.now().strftime("%Y%m%d")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def load_config() -> dict:
    """Load configuration from YAML file"""
    if not CONFIG_PATH.exists():
        logger.error(f"Config file not found: {CONFIG_PATH}")
        sys.exit(1)
    
    with open(CONFIG_PATH, 'r') as f:
        return yaml.safe_load(f)

def init_database():
    """Initialize SQLite database with schema"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT,
            price REAL,
            category TEXT,
            description TEXT,
            source_url TEXT,
            scraper_script TEXT,
            is_recursive BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(title, date, time, source_url)
        )
    ''')
    
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_events_date ON events(date)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_events_category ON events(category)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_events_price ON events(price)')
    
    conn.commit()
    conn.close()
    logger.info("Database initialized")

def get_date_range() -> tuple:
    """Get date range for next week (Monday to Sunday)"""
    today = datetime.now()
    # Find next Monday
    days_until_monday = (7 - today.weekday()) % 7
    if days_until_monday == 0:
        days_until_monday = 7
    
    start_date = today + timedelta(days=days_until_monday)
    end_date = start_date + timedelta(days=6)
    
    return start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')

def run_scraper(script_path: str, start_date: str, end_date: str) -> Optional[List[Dict]]:
    """Run individual scraper script"""
    if not Path(script_path).exists():
        logger.error(f"Scraper script not found: {script_path}")
        return None
    
    output_file = f'/tmp/events_{Path(script_path).stem}_{datetime.now().strftime("%Y%m%d%H%M%S")}.json'
    
    cmd = [
        'python3', script_path,
        '--start-date', start_date,
        '--end-date', end_date,
        '--output', output_file
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=SCRIPTS_DIR
        )
        
        if result.returncode != 0:
            logger.error(f"Scraper failed: {result.stderr}")
            return None
        
        if not Path(output_file).exists():
            logger.error(f"Output file not created: {output_file}")
            return None
        
        with open(output_file, 'r') as f:
            events = json.load(f)
        
        logger.info(f"Scraper extracted {len(events)} events")
        return events
        
    except subprocess.TimeoutExpired:
        logger.error(f"Scraper timed out: {script_path}")
        return None
    except Exception as e:
        logger.error(f"Scraper error: {str(e)}")
        return None

def enrich_missing_data(event: Dict) -> Dict:
    """Enrich event with missing data using web search or browser"""
    missing_fields = []
    
    if not event.get('description'):
        missing_fields.append('description')
    if not event.get('category'):
        missing_fields.append('category')
    if not event.get('price'):
        missing_fields.append('price')
    
    if not missing_fields:
        return event
    
    logger.info(f"Enriching event: {event.get('title')} - missing: {missing_fields}")
    
    # Placeholder for enrichment logic
    # This would use web_search or browser_navigate
    # For now, mark as needing manual review
    event['needs_manual_review'] = True
    
    return event

def categorize_event(event: Dict) -> str:
    """Categorize event based on title and description"""
    title = (event.get('title') or '').lower()
    desc = (event.get('description') or '').lower()
    
    music_keywords = ['concert', 'music', 'band', 'live', 'dj', 'festival', 'song']
    dance_keywords = ['dance', 'tanz', 'ballet', 'choreography', 'movement']
    social_keywords = ['meetup', 'networking', 'social', 'community', 'gathering', 'party']
    networking_keywords = ['networking', 'business', 'entrepreneur', 'startup', 'professional']
    
    if any(kw in title or kw in desc for kw in music_keywords):
        return 'music'
    elif any(kw in title or kw in desc for kw in dance_keywords):
        return 'dance'
    elif any(kw in title or kw in desc for kw in networking_keywords):
        return 'networking'
    elif any(kw in title or kw in desc for kw in social_keywords):
        return 'social'
    
    return 'unknown'

def filter_and_save_events(events: List[Dict], source_url: str, scraper_script: str):
    """Filter events by price and save to database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    saved_count = 0
    filtered_count = 0
    
    for event in events:
        # Filter by price (<= 15€ or free)
        price = event.get('price')
        if price is not None and price > 15.0:
            filtered_count += 1
            continue
        
        # Enrich missing data
        event = enrich_missing_data(event)
        
        # Categorize
        if not event.get('category'):
            event['category'] = categorize_event(event)
        
        # Check for recursive events (same title, different dates)
        cursor.execute(
            'SELECT COUNT(*) FROM events WHERE title = ? AND source_url = ?',
            (event.get('title'), source_url)
        )
        if cursor.fetchone()[0] > 0:
            event['is_recursive'] = True
        
        # Insert or update
        try:
            cursor.execute('''
                INSERT OR REPLACE INTO events 
                (title, date, time, price, category, description, source_url, scraper_script, is_recursive)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                event.get('title'),
                event.get('date'),
                event.get('time'),
                event.get('price'),
                event.get('category'),
                event.get('description'),
                source_url,
                scraper_script,
                event.get('is_recursive', False)
            ))
            saved_count += 1
        except Exception as e:
            logger.error(f"Failed to save event: {str(e)}")
    
    conn.commit()
    conn.close()
    
    logger.info(f"Saved {saved_count} events, filtered {filtered_count} events")
    return saved_count, filtered_count

def generate_report(saved_count: int, filtered_count: int, total_events: int):
    """Generate weekly summary report"""
    report_path = Path.home() / '.hermes' / 'event-scraper' / 'weekly-report.md'
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get category breakdown
    cursor.execute('''
        SELECT category, COUNT(*) 
        FROM events 
        WHERE date >= date('now')
        GROUP BY category
    ''')
    category_counts = cursor.fetchall()
    
    # Get price distribution
    cursor.execute('''
        SELECT 
            CASE 
                WHEN price IS NULL THEN 'Free'
                WHEN price <= 5 THEN '0-5€'
                WHEN price <= 10 THEN '5-10€'
                WHEN price <= 15 THEN '10-15€'
                ELSE '>15€'
            END as price_range,
            COUNT(*) as count
        FROM events
        WHERE date >= date('now')
        GROUP BY price_range
    ''')
    price_counts = cursor.fetchall()
    
    conn.close()
    
    report = f"""# Weekly Event Scraping Report
**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}

## Summary
- **Total Events Saved:** {saved_count}
- **Events Filtered (>15€):** {filtered_count}
- **Total Processed:** {total_events}

## Category Breakdown
"""
    
    for category, count in category_counts:
        report += f"- {category}: {count}\n"
    
    report += "\n## Price Distribution\n"
    for price_range, count in price_counts:
        report += f"- {price_range}: {count}\n"
    
    report += f"\n## Database Location\n{DB_PATH}\n"
    
    with open(report_path, 'w') as f:
        f.write(report)
    
    logger.info(f"Report generated: {report_path}")

def main():
    """Main orchestration function"""
    logger.info("Starting weekly event scraper")
    
    # Load configuration
    config = load_config()
    
    # Initialize database
    init_database()
    
    # Get date range
    start_date, end_date = get_date_range()
    logger.info(f"Scraping events from {start_date} to {end_date}")
    
    total_saved = 0
    total_filtered = 0
    total_processed = 0
    
    # Process each URL/script pair
    for url_config in config.get('urls', []):
        url = url_config['url']
        script_path = url_config['script']
        
        logger.info(f"Processing: {url}")
        
        # Run scraper
        events = run_scraper(script_path, start_date, end_date)
        
        if not events:
            logger.warning(f"No events extracted from {url}")
            continue
        
        # Filter and save
        saved, filtered = filter_and_save_events(
            events, 
            url, 
            script_path
        )
        
        total_saved += saved
        total_filtered += filtered
        total_processed += len(events)
    
    # Generate report
    generate_report(total_saved, total_filtered, total_processed)
    
    # Run validation cycle
    logger.info("Running validation cycle...")
    try:
        import subprocess
        result = subprocess.run(
            ['python3', str(Path.home() / '.hermes' / 'event-scraper' / 'validate_events.py')],
            capture_output=True,
            text=True,
            timeout=120
        )
        if result.returncode == 0:
            logger.info("Validation cycle completed successfully")
        else:
            logger.warning(f"Validation cycle had issues: {result.stderr}")
    except Exception as e:
        logger.error(f"Validation cycle failed: {e}")
    
    logger.info(f"Completed: {total_saved} events saved, {total_filtered} filtered")
    return 0

if __name__ == '__main__':
    sys.exit(main())
