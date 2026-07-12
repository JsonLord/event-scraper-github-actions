#!/usr/bin/env python3
"""
Firecrawl Agent Validation Script - Phase 2
Modified to use desk_agent_2.0 instead of Firecrawl API (placeholder)

Validates events scraped by Phase 1 (Jina/Jira reader) and retrieves missed events
Uses Desk Agent 2.0 API: http://localhost:7860 (placeholder)
"""

import os
import sys
import json
import sqlite3
import logging
import time
from pathlib import Path
from datetime import datetime, timedelta
import requests
from collections import defaultdict

# Configuration
DB_PATH = Path.home() / 'event-scraper' / 'events.db'
LOGS_DIR = Path.home() / 'event-scraper' / 'logs'

# Load environment variables from .env file
ENV_FILE = Path.home() / 'event-scraper' / '.env'
if ENV_FILE.exists():
    with open(ENV_FILE, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key.strip()] = value.strip()

# Desk Agent 2.0 Configuration (PLACEHOLDER)
# In a real implementation, these would be set via environment variables
DESK_AGENT_HOST = os.environ.get('DESK_AGENT_HOST', 'localhost')
DESK_AGENT_PORT = os.environ.get('DESK_AGENT_PORT', '7860')
DESK_AGENT_ENABLED = os.environ.get('DESK_AGENT_ENABLED = os.environ.get('DESK_AGENT_ENABLED', 'false').lower() == 'true'

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOGS_DIR / f'desk_agent_validation_{datetime.now().strftime("%Y%m%d")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def get_schedule_day():
    """
    Calculate which day of the 14-day cycle we're on.
    Uses a fixed epoch to ensure consistent scheduling.
    Epoch: 2024-01-06 (Saturday as Day 0)
    """
    epoch = datetime(2024, 1, 6).date()  # Saturday as date (Day 0 = Saturday)
    today = datetime.now().date()
    days_since_epoch = (today - epoch).days
    cycle_day = days_since_epoch % 14
    return cycle_day

def call_desk_agent(url: str, main_url: str, instructions: str) -> dict:
    """
    Call Desk Agent 2.0 for structured event extraction (PLACEHOLDER)
    
    Args:
        url: The main URL to crawl
        main_url: Reference to main website (for context)
        instructions: Instructions for the agent
        
    Returns:
        dict with structured event data (same format as Firecrawl for compatibility)
    """
    # Check if desk agent is enabled
    if not DESK_AGENT_ENABLED:
        logger.warning("Desk Agent 2.0 is disabled. Returning mock response.")
        # Return a mock successful response for testing/development
        return {
            'data': {
                'events': []  # Empty events list
            }
        }
    
    # Desk Agent 2.0 endpoint (placeholder - adjust based on actual API)
    agent_url = f'http://{DESK_AGENT_HOST}:{DESK_AGENT_PORT}/analyze'
    
    # Prepare payload - adjust based on actual Desk Agent 2.0 API specification
    payload = {
        'url': url,
        'instructions': instructions,
        # Add other parameters as needed by Desk Agent 2.0
        'model': 'desk-agent-2.0',  # Placeholder model name
        'format': 'json'
    }
    
    # Headers - adjust based on actual Desk Agent 2.0 requirements
    headers = {
        'Content-Type': 'application/json'
        # Add authentication if needed: 'Authorization': f'Bearer {DESK_AGENT_API_KEY}'
    }
    
    try:
        logger.info(f"Calling Desk Agent 2.0 at {agent_url}")
        
        # Start agent job
        response = requests.post(
            agent_url,
            json=payload,
            headers=headers,
            timeout=30
        )
        
        if response.status_code != 200:
            logger.error(f"Desk Agent 2.0 error: {response.status_code} - {response.text[:300]}")
            return {'error': f'API error: {response.status_code}', 'text': response.text}
        
        job_data = response.json()
        job_id = job_data.get('id')
        
        if not job_id:
            logger.error("No job ID returned from Desk Agent 2.0")
            return {'error': 'No job ID returned'}
        
        logger.info(f"Desk Agent 2.0 job started: {job_id}")
        
        # Poll for completion (adjust based on actual Desk Agent 2.0 behavior)
        status_url = f'http://{DESK_AGENT_HOST}:{DESK_AGENT_PORT}/status/{job_id}'
        max_wait = 300  # 5 minutes
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            status_response = requests.get(
                status_url,
                headers=headers,
                timeout=10
            )
            
            if status_response.status_code != 200:
                logger.error(f"Status check failed: {status_response.status_code}")
                time.sleep(5)
                continue
            
            status_data = status_response.json()
            status = status_data.get('status')
            
            # Log progress every 30 seconds
            elapsed = int(time.time() - start_time)
            if elapsed % 30 == 0 and status in ['processing', 'running', 'pending']:
                logger.info(f"Desk Agent still working ({elapsed}s): {status}")
            
            if status == 'completed':
                logger.info(f"Desk Agent 2.0 job completed: {job_id}")
                return status_data.get('data', {})
            elif status == 'failed':
                logger.error(f"Desk Agent 2.0 job failed: {status_data.get('error')}")
                return {'error': f"Job failed: {status_data.get('error')}"}
            elif status in ['running', 'pending', 'processing', 'scraping', 'searching']:
                time.sleep(5)
            else:
                logger.warning(f"Unknown status: {status}")
                time.sleep(5)
        
        logger.error(f"Desk Agent 2.0 job timed out: {job_id}")
        return {'error': 'Job timed out'}
        
    except Exception as e:
        logger.error(f"Desk Agent 2.0 failed for {url}: {str(e)}")
        return {'error': str(e)}

def extract_events_from_desk_agent(result: dict, source_url: str) -> list:
    """
    Extract structured event data from Desk Agent 2.0 response
    (Maintains same interface as extract_events_from_firecrawl for compatibility)
    
    Args:
        result: Response from Desk Agent 2.0
        source_url: The source URL that was analyzed
        
    Returns:
        List of event dictionaries in the standard format
    """
    events = []
    
    if 'error' in result:
        return events
    
    # Get structured data from Desk Agent 2.0 response
    # Adjust this based on actual Desk Agent 2.0 response format
    data = result.get('data', {})
    extracted_events = data.get('events', [])
    
    logger.info(f"Extracted {len(extracted_events)} structured events from {source_url}")
    
    # Convert to our standard format (matches Firecrawl format for compatibility)
    for event in extracted_events:
        events.append({
            'title': event.get('title', ''),
            'date': event.get('date', ''),
            'time': event.get('time', ''),
            'price': event.get('price', ''),
            'category': event.get('category', ''),
            'description': event.get('description', ''),
            'url': event.get('url', source_url),
            'venue': event.get('venue', ''),
            'source_url': source_url
        })
    
    return events

def get_existing_events(source_url: str, days: int = 7) -> list:
    """Get events already captured by Phase 1 scraper from database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT title, date, time, price, category, description, source_url
        FROM events
        WHERE source_url = ? 
        AND date >= date('now', '-' || ? || ' days')
        AND date <= date('now', '+14 days')
    ''', (source_url, days))
    
    events = cursor.fetchall()
    conn.close()
    return events

def validate_and_retrieve_missed(source_url: str, site_name: str, phase1_events: list) -> dict:
    """
    Validate Phase 1 scraping and retrieve missed events using Desk Agent 2.0
    
    The Agent is steered with:
    - Events already found by Phase 1 (Jina/Jira reader)
    - Sub-URLs discovered during Phase 1 scraping
    - Instructions to find ONLY missing events
    
    Returns:
        dict with validation results and any missed events found
    """
    logger.info(f"Validating: {site_name} ({source_url})")
    
    # Get events already captured by Phase 1
    existing_events = get_existing_events(source_url, days=14)
    existing_titles = {event[0].lower() for event in existing_events}
    
    logger.info(f"Phase 1 captured {len(existing_events)} events from {site_name}")
    
    # Format Phase 1 events as context for the Agent
    phase1_context = ""
    if existing_events:
        phase1_context = "\n".join([
            f"- {event[0]} on {event[1]} at {event[2] or 'TBD'} ({event[4] or 'uncategorized'})"
            for event in existing_events[:20]  # First 20 events
        ])
    
    # Instructions for Desk Agent 2.0 - STEERED approach
    instructions = f"""
You are validating event scraping for a Berlin events website.

MAIN WEBSITE: {source_url}
SITE NAME: {site_name}

YOUR TASK: Find events that were MISSED by the initial scraper.

EVENTS ALREADY FOUND (do NOT report these again):
{phase1_context if phase1_context else "None - this is a fresh scrape"}

INSTRUCTIONS:
1. Navigate this website and discover ALL event pages (check navigation, calendars, program listings)
2. Extract ALL events happening in the next 14 days
3. Compare with the "Events Already Found" list above
4. ONLY report events that are NOT in that list (the missed ones)
5. Be thorough - check ALL sub-pages, not just the homepage

For each MISSED event, extract:
- title: Event name
- date: YYYY-MM-DD format
- time: HH:MM format (or "TBD")
- venue: Location name
- category: Type of event (Theater, Concert, Workshop, etc.)
- price: Ticket price or "free"
- url: Direct link to event page
- description: Brief summary

Return ONLY the events that were MISSED (not in the "Events Already Found" list).
If all events were already found, return an empty array.
"""

    # Call Desk Agent 2.0 with steered instructions
    result = call_desk_agent(source_url, source_url, instructions)
    
    if 'error' in result:
        return {
            'site': site_name,
            'url': source_url,
            'success': False,
            'error': result['error'],
            'phase1_events': len(existing_events),
            'desk_agent_events': 0,
            'missed_events': 0,
            'sub_urls_discovered': 0
        }
    
    # Extract events from Desk Agent 2.0 response
    desk_agent_events = extract_events_from_desk_agent(result, source_url)
    
    # Find truly missed events (in Desk Agent but not in database)
    desk_agent_titles = {event.get('title', '').lower() for event in desk_agent_events}
    missed_titles = desk_agent_titles - existing_titles
    
    missed_events = [e for e in desk_agent_events if e.get('title', '').lower() in missed_titles]
    
    logger.info(f"Desk Agent found {len(desk_agent_events)} events, {len(missed_events)} potentially missed")
    
    return {
        'site': site_name,
        'url': source_url,
        'success': True,
        'phase1_events': len(existing_events),
        'desk_agent_events': len(desk_agent_events),
        'missed_events': len(missed_events),
        'missed_event_titles': [e.get('title') for e in missed_events[:10]],
        'sub_urls_discovered': 0,  # Agent discovers internally
        'events': missed_events
    }

def save_missed_events(missed_events: list, source_url: str):
    """Save missed events to database for manual review or enrichment"""
    if not missed_events:
        return 0
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    added = 0
    for event in missed_events:
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO events 
                (title, date, time, price, category, description, source_url, scraper_script, is_recursive)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                event.get('title'),
                event.get('date', datetime.now().strftime('%Y-%m-%d')),
                event.get('time', '12:00'),
                event.get('price', 0),
                event.get('category', 'needs_review'),
                event.get('description', ''),
                source_url,
                'desk_agent_validation',
                0
            ))
            added += 1
        except Exception as e:
            logger.error(f"Failed to save missed event: {event.get('title')} - {e}")
    
    conn.commit()
    conn.close()
    logger.info(f"Saved {added} missed events to database")
    return added

def update_scraper_script_immediate(source_url: str, rec: dict, events: list) -> bool:
    """Immediately update a Phase 1 scraper script based on missed events"""
    try:
        import yaml
        
        # Load config to find scraper script
        CONFIG_PATH = Path.home() / 'event-scraper' / 'config.yaml'
        if not CONFIG_PATH.exists():
            logger.warning(f"Config not found: {CONFIG_PATH}")
            return False
        
        with open(CONFIG_PATH, 'r') as f:
            config = yaml.safe_load(f)
        
        scraper_script = None
        for url_config in config.get('urls', []):
            if url_config['url'] == source_url:
                scraper_script = url_config['script']
                break
        
        if not scraper_script:
            logger.warning(f"No scraper script found for {source_url}")
            return False
        
        script_path = Path(scraper_script)
        if not script_path.exists():
            logger.warning(f"Scraper script not found: {script_path}")
            return False
        
        # Read current script
        with open(script_path, 'r') as f:
            script_content = f.read()
        
        # Generate improvement notes
        improvement_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        missed_titles = [e.get('title', 'Unknown') for e in events[:5]]
        
        improvement_header = f"""
# ============================================
# AUTO-IMPROVEMENT - {improvement_date}
# ============================================
# Desk Agent 2.0 found {len(events)} missed events that Phase 1 missed:
# 
# Missed events:
"""
        for title in missed_titles:
            improvement_header += f"#   - {title}\n"
        
        improvement_header += f"\n# Action: Review and enhance event extraction logic for this site\n"
        improvement_header += f"# Priority: {rec['priority'].upper()}\n"
        improvement_header += f"# Recommendation: {rec['suggestion']}\n\n"
        
        # Check if this improvement marker already exists recently
        if f"AUTO-IMPROVEMENT - {improvement_date[:10]}" in script_content:
            logger.info(f"Improvement already applied today for {source_url}")
            return False
        
        # Prepend improvement header
        new_content = improvement_header + script_content
        
        # Write updated script
        with open(script_path, 'w') as f:
            f.write(new_content)
        
        logger.info(f"✅ Auto-improved scraper: {script_path}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to auto-update scraper script: {e}")
        return False

def run_daily_batch(cycle_day: int):
    """Run the scheduled batch for the current day of the 14-day cycle"""
    # This would normally load from SCHEDULE_14_DAY_CYCLE
    # For now, we'll use a simplified version
    sites = []  # Would be populated from config
    
    if not sites:
        logger.info(f"No sites scheduled for Day {cycle_day} (rest day)")
        return []
    
    logger.info(f"Running Day {cycle_day} batch: {len(sites)} sites")
    
    results = []
    all_missed_events = []
    
    for site_name, url in sites:
        # Get Phase 1 events for this site
        phase1_events = get_existing_events(url, days=14)
        
        result = validate_and_retrieve_missed(url, site_name, phase1_events)
        
        # Save missed events
        if result.get('success') and result.get('events'):
            save_missed_events(result['events'], url)
            all_missed_events.extend(result['events'])
        
        results.append(result)
    
    # Run immediate improvement cycle if we found missed events
    if all_missed_events:
        logger.info(f"Running immediate improvement cycle for {len(all_missed_events)} missed events")
        # run_immediate_improvement_cycle(all_missed_events)  # Would implement this
    
    return results

def generate_validation_report(results: list, cycle_day: int, day_name: str):
    """Generate validation report"""
    report_path = Path.home() / '.hermes' / 'event-scraper' / f'desk_agent_validation_{datetime.now().strftime("%Y%m%d")}.md'
    
    if not results:
        report = f"""# Desk Agent 2.0 Validation Report - Phase 2
**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}
**Cycle Day:** {cycle_day} ({day_name})
**Status:** Rest day - no sites scheduled

## Notes
- 14-day cycle with fixed daily batches
- Desk Agent 2.0 integration (placeholder)
- Next run: Tomorrow (Day {(cycle_day + 1) % 14})
"""
        with open(report_path, 'w') as f:
            f.write(report)
        logger.info(f"Validation report saved: {report_path}")
        return report_path
    
    successful = sum(1 for r in results if r.get('success'))
    failed = len(results) - successful
    total_phase1_events = sum(r.get('phase1_events', 0) for r in results)
    total_desk_agent_events = sum(r.get('desk_agent_events', 0) for r in results)
    total_missed = sum(r.get('missed_events', 0) if isinstance(r.get('missed_events'), int) else len(r.get('missed_events', [])) for r in results)
    total_sub_urls = sum(r.get('sub_urls_discovered', 0) for r in results)
    
    report = f"""# Desk Agent 2.0 Validation Report - Phase 2
**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}
**Cycle Day:** {cycle_day} ({day_name})
**14-Day Cycle:** Sites {cycle_day + 1} of 14

## Summary
- **Sites Validated:** {len(results)} (max 5 agent runs/day)
- **Successful:** {successful}
- **Failed:** {failed}
- **Phase 1 Events (Jina):** {total_phase1_events}
- **Desk Agent Events Found:** {total_desk_agent_events}
- **Missed Events Retrieved:** {total_missed}
- **Sub-URLs Discovered:** {total_sub_urls}

## Detailed Results
"""
    
    for result in results:
        status = "✅" if result.get('success') else "❌"
        report += f"\n### {status} {result['site']}\n"
        report += f"- URL: {result['url']}\n"
        report += f"- Phase 1 Events: {result.get('phase1_events', 0)}\n"
        report += f"- Desk Agent Events: {result.get('desk_agent_events', 0)}\n"
        report += f"- Missed Events: {result.get('missed_events', 0)}\n"
        report += f"- Sub-URLs Discovered: {result.get('sub_urls_discovered', 0)}\n"
        
        if result.get('error'):
            report += f"- **Error:** {result['error']}\n"
        
        if result.get('missed_event_titles'):
            report += "\n**Missed Event Titles:**\n"
            for title in result['missed_event_titles'][:5]:
                report += f"  - {title}\n"
    
    report += f"\n## 14-Day Schedule\n"
    report += f"- **Today:** Day {cycle_day} ({day_name})\n"
    report += f"- **Next:** Day {(cycle_day + 1) % 14} ({['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][(cycle_day + 1) % 7]})\n"
    report += f"- **Cycle repeats every 14 days**\n"
    
    report += f"\n## Database Location\n{DB_PATH}\n"
    report += f"\n## Notes\n"
    report += "- Phase 1 uses Jina/Jira reader for initial scraping\n"
    report += "- Phase 2 uses Desk Agent 2.0 for validation and missed event retrieval\n"
    report += "- Max 5 agent runs per day\n"
    report += "- Fixed 14-day cycle with recurring daily batches\n"
    report += "- Missed events saved to database with category 'needs_review'\n"
    
    with open(report_path, 'w') as f:
        f.write(report)
    
    logger.info(f"Validation report saved: {report_path}")
    return report_path

def main():
    """Main validation function"""
    logger.info("="*60)
    logger.info("Starting Desk Agent 2.0 Validation - Phase 2")
    logger.info("="*60)
    
    # Check for command-line argument to override cycle day (for testing)
    cycle_day = None
    if len(sys.argv) > 1:
        try:
            cycle_day = int(sys.argv[1])
            if 0 <= cycle_day <= 13:
                logger.info(f"Override: Running Day {cycle_day} batch (test mode)")
            else:
                logger.warning(f"Invalid cycle day {cycle_day}, using auto-calculation")
                cycle_day = None
        except ValueError:
            logger.warning(f"Invalid argument '{sys.argv[1]}', using auto-calculation")
    
    # Calculate which day of the 14-day cycle we're on (if not overridden)
    if cycle_day is None:
        cycle_day = get_schedule_day()
    
    day_names = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
    day_name = day_names[cycle_day % 7]
    
    logger.info(f"14-Day Cycle: Day {cycle_day} of 14 ({day_name})")
    
    # Run the scheduled batch for this day
    results = run_daily_batch(cycle_day)
    
    # Generate report
    report_path = generate_validation_report(results, cycle_day, day_name)
    
    # Print summary
    print(f"\n{'='*60}")
    print(f"Desk Agent 2.0 Validation Complete - Phase 2")
    print(f"{'='*60}")
    print(f"Cycle Day: {cycle_day} of 14 ({day_name})")
    print(f"Sites processed: {len(results)}")
    print(f"Report: {report_path}")
    print(f"Next run: Day {(cycle_day + 1) % 14} ({day_names[(cycle_day + 1) % 7]})")
    print(f"{'='*60}\n")
    
    return 0

if __name__ == '__main__':
    sys.exit(main())