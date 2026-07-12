"""
Jules Manual Review

Jules AI manually reviews scraped events by:
1. Loading the scraped data and HTML from the scrape branch
2. Simulating manual browsing to find missed events
3. Adding missed events to the event list
4. Categorizing events based on category config
5. Generating improved scraper code

Output: review_results.json with all events (including missed ones) and improved scrapers
"""

import os
import sys
import json
import glob
import argparse
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from jules_client import JulesClient, JulesClientError

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class JulesManualReview:
    """
    Jules AI manually reviews scraped events and improves them.
    """
    
    def __init__(self, agent_id: str = "jules-1"):
        self.jules = JulesClient(agent_id)
    
    def load_category_config(self, config_path: str) -> Dict[str, Any]:
        """Load category configuration"""
        with open(config_path) as f:
            return yaml.safe_load(f)
    
    def categorize_event(
        self,
        event: Dict[str, Any],
        categories: Dict[str, Any]
    ) -> str:
        """
        Categorize an event based on title, description, and keywords.
        """
        text = f"{event.get('title', '')} {event.get('description', '')}".lower()
        
        for category, config in categories.get('categories', {}).items():
            for keyword in config.get('keywords', []):
                if keyword.lower() in text:
                    return category
        
        return categories.get('default_category', 'social')
    
    def review_and_improve(
        self,
        scrape_data: Dict[str, Any],
        html_content: str,
        category_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Jules AI reviews scraped data, finds missed events, and improves scrapers.
        
        Args:
            scrape_data: Raw scraped events
            html_content: Full HTML of the page
            category_config: Category configuration
        
        Returns:
            Review results with improved events and scraper code
        """
        logger.info("Starting Jules manual review...")
        
        prompt = f"""
        MANUAL EVENT REVIEW AND IMPROVEMENT
        
        You are manually reviewing scraped events as if browsing the website yourself.
        
        CURRENTLY SCRAPED EVENTS:
        {json.dumps(scrape_data.get('events', [])[:20], indent=2)}
        
        FULL PAGE HTML (first 80k chars):
        {html_content[:80000]}
        
        CATEGORIES (use these for classification):
        {json.dumps(category_config.get('categories', {}), indent=2)}
        
        TASKS:
        
        1. MANUAL REVIEW - Browse the HTML as if you were a user:
           - Find ALL events on the page
           - Look in sidebars, modals, tabs, lazy-loaded sections
           - Check pagination, "load more" buttons
           - Identify events that were MISSED by the scraper
        
        2. ADD MISSED EVENTS:
           - Extract complete event data for missed events
           - Include: title, date, time, price, venue, description, url, category
        
        3. CATEGORIZE ALL EVENTS:
           - Assign each event to one of the categories above
           - Use keywords from title/description to determine category
           - Default to "social" if unsure
        
        4. IMPROVE SCRAPER CODE:
           - Analyze WHY missed events were not captured
           - Generate IMPROVED scraper code that catches these patterns
           - Keep working selectors, add new ones for missed patterns
           - Make it GENERAL (not just for these specific events)
        
        Return JSON with:
        {{
            "reviewed_at": "timestamp",
            "original_count": <number>,
            "missed_count": <number>,
            "total_count": <number>,
            "all_events": [
                {{
                    "title": "...",
                    "date": "YYYY-MM-DD",
                    "time": "HH:MM",
                    "price": 12.50,
                    "category": "music",
                    "description": "...",
                    "url": "...",
                    "venue": "...",
                    "source_url": "...",
                    "added_by": "jules_review"  // or "original_scraper"
                }}
            ],
            "improved_scraper_code": "```python\\n...improved code...\\n```",
            "improvements_made": [
                "Added selector for sidebar events",
                "Handle lazy-loaded content",
                "Parse alternative date formats"
            ],
            "category_distribution": {{
                "music": 5,
                "social": 12,
                ...
            }}
        }}
        """
        
        try:
            session = self.jules.create_session(
                prompt=prompt,
                title="Manual Event Review and Improvement",
                source_id=os.environ.get("JULES_SOURCE_ID"),
                branch="main"
            )
            
            session_id = session["name"].split("/")[-1]
            logger.info(f"Created review session: {session_id}")
            
            # Wait for completion
            result = self.jules.wait_for_session(session_id, timeout=1800)
            
            # Extract review results
            review = self._extract_review(result)
            
            if review:
                logger.info(f"✓ Review complete: {review.get('missed_count', 0)} missed events found")
                return review
            else:
                logger.warning("⚠ Jules session completed but no review extracted")
                return self._default_review(scrape_data)
                
        except JulesClientError as e:
            logger.error(f"✗ Jules session failed: {e}")
            return self._default_review(scrape_data)
    
    def _extract_review(self, session: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract review results from Jules session"""
        outputs = session.get("outputs", [])
        
        for output in outputs:
            if output.get("text"):
                text = output["text"]
                
                # Try to parse JSON
                try:
                    if "{" in text:
                        start = text.find("{")
                        brace_count = 0
                        end = start
                        for i, char in enumerate(text[start:]):
                            if char == "{":
                                brace_count += 1
                            elif char == "}":
                                brace_count -= 1
                                if brace_count == 0:
                                    end = start + i + 1
                                    break
                        
                        json_str = text[start:end]
                        return json.loads(json_str)
                except json.JSONDecodeError:
                    pass
                
                # Try code block
                if "```json" in text:
                    start = text.find("```json") + 8
                    end = text.find("```", start)
                    if end > start:
                        try:
                            return json.loads(text[start:end].strip())
                        except:
                            pass
        
        return None
    
    def _default_review(self, scrape_data: Dict[str, Any]) -> Dict[str, Any]:
        """Return default review if Jules fails"""
        events = scrape_data.get('events', [])
        return {
            "reviewed_at": datetime.now().isoformat(),
            "original_count": len(events),
            "missed_count": 0,
            "total_count": len(events),
            "all_events": events,
            "improved_scraper_code": None,
            "improvements_made": [],
            "category_distribution": {}
        }


def main():
    parser = argparse.ArgumentParser(description="Jules Manual Review")
    parser.add_argument("--branch", required=True, help="Scrape branch name")
    parser.add_argument("--category-config", required=True, help="Path to category YAML")
    parser.add_argument("--output", required=True, help="Output path for review results")
    parser.add_argument("--agent-id", default="jules-1", help="Jules agent ID")
    
    args = parser.parse_args()
    
    # Load environment
    if not os.environ.get("JULES_API_KEY"):
        print("Error: JULES_API_KEY not set")
        sys.exit(1)
    
    # Load category config
    category_config = JulesManualReview().load_category_config(args.category_config)
    
    # Load all scrape data
    all_events = []
    scrape_files = glob.glob("docs/scrape-data/raw_*.json")
    
    for filepath in scrape_files:
        with open(filepath) as f:
            data = json.load(f)
            all_events.extend(data.get('events', []))
            logger.info(f"Loaded {len(data.get('events', []))} events from {filepath}")
    
    # Load HTML for first source (simplified - would need to load per-source)
    html_files = glob.glob("docs/scrape-data/html/*.html")
    html_content = ""
    if html_files:
        with open(html_files[0]) as f:
            html_content = f.read()
    
    # Create initial scrape data structure
    scrape_data = {
        "events": all_events,
        "source": "combined"
    }
    
    # Run Jules review
    review = JulesManualReview(agent_id=args.agent_id)
    results = review.review_and_improve(
        scrape_data=scrape_data,
        html_content=html_content,
        category_config=category_config
    )
    
    # Save results
    results["branch"] = args.branch
    results["reviewed_at"] = datetime.now().isoformat()
    
    with open(args.output, "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"✓ Review results saved to {args.output}")
    print(f"  Original events: {results.get('original_count', 0)}")
    print(f"  Missed events found: {results.get('missed_count', 0)}")
    print(f"  Total events: {results.get('total_count', 0)}")
    print(f"  Improvements: {len(results.get('improvements_made', []))}")


if __name__ == "__main__":
    main()
