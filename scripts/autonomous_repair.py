import os
import sys
import json
import subprocess
import logging
import argparse
from pathlib import Path
from typing import Optional

# Ensure we can import scripts in the same directory
sys.path.insert(0, os.path.dirname(__file__))

from jules_analysis import CompletenessAnalyzer
from jules_scraper_generator import ScraperGenerator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

class AutonomousRepair:
    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries
        self.analyzer = CompletenessAnalyzer()
        self.generator = ScraperGenerator()

    def run_scraper(self, script_path: str, url: str, output_path: str, html_path: str) -> bool:
        """Run a scraper and return True if successful (found events)."""
        logger.info(f"Running scraper: {script_path} for {url}")

        # Ensure directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        os.makedirs(os.path.dirname(html_path), exist_ok=True)

        cmd = [
            "python3", script_path,
            "--url", url,
            "--output", output_path,
            "--save-html"
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

            if result.returncode != 0:
                logger.error(f"Scraper execution failed: {result.stderr}")
                return False

            if not os.path.exists(output_path):
                logger.error(f"Output file not found: {output_path}")
                return False

            with open(output_path, 'r') as f:
                data = json.load(f)
                count = data.get("event_count", 0)
                if count == 0:
                    logger.warning("Scraper returned 0 events.")
                    return False

                # Check for mandatory fields in the first event if any
                events = data.get("events", [])
                if events:
                    first_event = events[0]
                    if not first_event.get("price") and first_event.get("price") != 0:
                        logger.warning("Mandatory field 'price' missing from events.")
                        # This might be worth a repair if it's consistent

            logger.info(f"Scraper succeeded with {count} events.")
            return True

        except Exception as e:
            logger.error(f"Error running scraper: {e}")
            return False

    def repair_cycle(self, script_path: str, url: str, site_name: str):
        """Execute the autonomous repair loop."""
        output_path = f"data/raw_{site_name}.json"
        html_path = f"data/html/{site_name}.html"

        for attempt in range(1, self.max_retries + 1):
            logger.info(f"Attempt {attempt}/{self.max_retries} for {site_name}")

            success = self.run_scraper(script_path, url, output_path, html_path)

            if success:
                logger.info(f"Repair cycle successful for {site_name} on attempt {attempt}")
                return True

            if attempt == self.max_retries:
                logger.error(f"Max retries reached for {site_name}. Repair failed.")
                return False

            logger.info(f"Initiating Jules repair for {site_name}...")

            # 1. Analyze failure
            # We need the HTML to analyze
            if not os.path.exists(html_path):
                # If HTML wasn't saved by the scraper, we can't analyze easily
                # In a real scenario, we might use a generic fetcher to get the HTML
                logger.error(f"HTML not found at {html_path}, cannot perform analysis.")
                continue

            with open(html_path, 'r') as f:
                raw_html = f.read()

            scraped_events = []
            if os.path.exists(output_path):
                with open(output_path, 'r') as f:
                    try:
                        scraped_events = json.load(f).get("events", [])
                    except:
                        pass

            analysis = self.analyzer.analyze(site_name, raw_html, scraped_events)

            if not analysis.get("needs_update", True) and len(scraped_events) == 0:
                # If Jules thinks it doesn't need an update but we got 0 events,
                # maybe force an update or check if the site is actually empty
                logger.warning("Jules thinks no update needed, but 0 events found. Forcing repair.")

            # 2. Generate fix
            with open(script_path, 'r') as f:
                current_code = f.read()

            new_code = self.generator.generate(site_name, analysis, current_code)

            if new_code:
                with open(script_path, 'w') as f:
                    f.write(new_code)
                logger.info(f"Applied improved code to {script_path}")
            else:
                logger.error("Failed to generate improved code.")
                continue

        return False

def main():
    parser = argparse.ArgumentParser(description="Autonomous Scraper Repair")
    parser.add_argument("--script", required=True, help="Path to the scraper script")
    parser.add_argument("--url", required=True, help="URL to scrape")
    parser.add_argument("--site-name", required=True, help="Site name for output files")
    parser.add_argument("--retries", type=int, default=3, help="Max repair retries")

    args = parser.parse_args()

    repair = AutonomousRepair(max_retries=args.retries)
    success = repair.repair_cycle(args.script, args.url, args.site_name)

    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
