"""
Apply Jules Improvements

Takes the review results and:
1. Updates scraper files with improved code
2. Saves the complete event list (including missed events)
3. Prepares data for GitHub Pages deployment
"""

import os
import sys
import json
import argparse
import logging
from datetime import datetime
from typing import Dict, Any

import yaml

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def apply_improvements(review_results: Dict[str, Any], output_dir: str):
    """
    Apply Jules improvements to scraper files.
    
    Args:
        review_results: Results from Jules manual review
        output_dir: Directory to save improved scraper files
    """
    improved_code = review_results.get("improved_scraper_code")
    
    if not improved_code:
        logger.info("No improved scraper code to apply")
        return
    
    # Extract code from markdown block if present
    if "```python" in improved_code:
        start = improved_code.find("```python") + 10
        end = improved_code.find("```", start)
        if end > start:
            improved_code = improved_code[start:end].strip()
    
    # Save to a generic improved scraper file
    output_file = os.path.join(output_dir, "improved_event_scraper.py")
    with open(output_file, "w") as f:
        f.write(improved_code)
    
    logger.info(f"✓ Saved improved scraper to {output_file}")
    
    # Also save improvements as a patch file
    improvements = review_results.get("improvements_made", [])
    patch_file = os.path.join(output_dir, "scraper_improvements.yaml")
    
    patch_data = {
        "applied_at": datetime.now().isoformat(),
        "improvements": improvements,
        "missed_events_found": review_results.get("missed_count", 0),
        "total_events": review_results.get("total_count", 0)
    }
    
    with open(patch_file, "w") as f:
        yaml.dump(patch_data, f, default_flow_style=False)
    
    logger.info(f"✓ Saved improvements to {patch_file}")


def update_events_file(review_results: Dict[str, Any], output_dir: str):
    """
    Update the events.json file with all events (including missed ones).
    """
    all_events = review_results.get("all_events", [])
    
    # Filter by price (≤15€) and date (within 14 days)
    from datetime import datetime, timedelta
    
    max_price = 15
    cutoff_date = datetime.now() + timedelta(days=14)
    
    filtered_events = []
    for event in all_events:
        price = event.get("price", 0) or 0
        if price > max_price:
            continue
        
        # Date filtering would go here
        filtered_events.append(event)
    
    # Create final events structure
    events_data = {
        "scraped_at": review_results.get("reviewed_at", datetime.now().isoformat()),
        "total_events": len(filtered_events),
        "category_distribution": review_results.get("category_distribution", {}),
        "events": filtered_events
    }
    
    # Save to docs/events.json
    output_file = os.path.join(output_dir, "events.json")
    with open(output_file, "w") as f:
        json.dump(events_data, f, indent=2)
    
    logger.info(f"✓ Saved {len(filtered_events)} filtered events to {output_file}")


def main():
    parser = argparse.ArgumentParser(description="Apply Jules Improvements")
    parser.add_argument("--review-results", required=True, help="Path to review results JSON")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    
    args = parser.parse_args()
    
    # Load review results
    with open(args.review_results) as f:
        review_results = json.load(f)
    
    # Ensure output directory exists
    os.makedirs(args.output_dir, exist_ok=True)
    os.makedirs(os.path.join(args.output_dir, "docs"), exist_ok=True)
    
    # Apply improvements to scraper files
    apply_improvements(review_results, args.output_dir)
    
    # Update events file
    update_events_file(review_results, os.path.join(args.output_dir, "docs"))
    
    print("✓ All improvements applied successfully")


if __name__ == "__main__":
    main()
