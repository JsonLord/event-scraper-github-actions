"""
Scraper Improvement Cycle with Jules AI

This script analyzes validation results and uses Jules to automatically
improve scraper scripts to catch previously missed events.

Workflow:
1. Run scraper and collect events
2. Run validation to find missed events
3. Analyze differences between scraped and missed events
4. Use Jules to generate improved scraper logic
5. Commit improvements to repository
6. Create PR with changes
"""

import os
import sys
import json
import argparse
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'scripts'))

from jules_client import JulesClient, JulesClientError

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class ScraperImprover:
    """
    Uses Jules AI to automatically improve scraper scripts based on validation results.
    """
    
    def __init__(
        self,
        agent_id: str = "jules-1",
        source_id: Optional[str] = None,
        github_token: Optional[str] = None
    ):
        """
        Initialize the scraper improver.
        
        Args:
            agent_id: Jules agent to use
            source_id: GitHub repository source for Jules
            github_token: GitHub token for PR creation
        """
        self.jules = JulesClient(agent_id)
        self.source_id = source_id
        self.github_token = github_token or os.environ.get("GITHUB_TOKEN")
        
    def analyze_missed_events(
        self,
        scraped_events: List[Dict[str, Any]],
        missed_events: List[Dict[str, Any]],
        site_html: str,
        site_url: str
    ) -> Dict[str, Any]:
        """
        Analyze why certain events were missed.
        
        Args:
            scraped_events: Events successfully scraped
            missed_events: Events that were missed (from validation)
            site_html: Full HTML of the page
            site_url: Source URL
        
        Returns:
            Analysis of missed event patterns
        """
        logger.info(f"Analyzing {len(missed_events)} missed events")
        
        if not missed_events:
            return {
                "status": "complete",
                "message": "No missed events to analyze",
                "improvements_needed": False
            }
        
        # Extract patterns from missed events
        missed_patterns = self._extract_missed_patterns(missed_events, site_html)
        
        return {
            "status": "analysis_complete",
            "scraped_count": len(scraped_events),
            "missed_count": len(missed_events),
            "missed_patterns": missed_patterns,
            "improvements_needed": len(missed_patterns) > 0
        }
    
    def _extract_missed_patterns(
        self,
        missed_events: List[Dict[str, Any]],
        site_html: str
    ) -> List[Dict[str, Any]]:
        """Extract common patterns from missed events"""
        patterns = []
        
        for event in missed_events:
            # Analyze event structure
            pattern = {
                "title": event.get("title", "Unknown"),
                "likely_location": self._guess_event_location(event, site_html),
                "price_indicator": event.get("price_indicator", "unknown"),
                "date_format": event.get("date_format", "unknown"),
                "container_type": self._guess_container_type(event, site_html)
            }
            patterns.append(pattern)
        
        return patterns
    
    def _guess_event_location(self, event: Dict, html: str) -> str:
        """Guess where the event data is located in HTML"""
        # Simplified - would need actual HTML parsing
        return "unknown - requires HTML analysis"
    
    def _guess_container_type(self, event: Dict, html: str) -> str:
        """Guess the HTML container type for the event"""
        # Simplified - would need actual HTML analysis
        return "unknown - requires HTML analysis"
    
    def generate_improvement_with_jules(
        self,
        site_name: str,
        site_url: str,
        current_scraper_code: str,
        missed_event_analysis: Dict[str, Any],
        missed_events_sample: List[Dict[str, Any]]
    ) -> Optional[str]:
        """
        Use Jules to generate improved scraper code.
        
        Args:
            site_name: Name of the event site
            site_url: URL of the event site
            current_scraper_code: Current scraper script code
            missed_event_analysis: Analysis of missed events
            missed_events_sample: Sample of missed events
        
        Returns:
            Improved scraper code, or None if generation failed
        """
        logger.info("Generating improved scraper with Jules AI...")
        
        prompt = f"""
        IMPROVE THIS EVENT SCRAPER
        
        Site: {site_name} ({site_url})
        
        CURRENT SCRAPER CODE:
        ```python
        {current_scraper_code}
        ```
        
        MISSED EVENTS ANALYSIS:
        {json.dumps(missed_event_analysis, indent=2)}
        
        SAMPLE MISSED EVENTS:
        {json.dumps(missed_events_sample[:5], indent=2)}
        
        TASK:
        Create an improved version of the scraper that catches the missed events.
        
        Requirements:
        1. Keep the existing functionality that works
        2. Add selectors/parsing logic for the missed event patterns
        3. Handle multiple event container types if needed
        4. Maintain price filtering (≤15€) and date range (14 days)
        5. Return the same event schema: title, date, time, price, category, description, url, venue, source_url
        
        IMPORTANT: This is a GENERAL improvement, not just for these specific events.
        The scraper should adapt to catch similar events in the future.
        
        Return ONLY the improved Python code, no explanations.
        """
        
        try:
            session = self.jules.create_session(
                prompt=prompt,
                title=f"Scraper Improvement: {site_name}",
                source_id=self.source_id,
                branch="main"
            )
            
            session_id = session["name"].split("/")[-1]
            logger.info(f"Created Jules session: {session_id}")
            
            # Wait for completion
            result = self.jules.wait_for_session(session_id, timeout=1800)
            
            # Extract improved code
            improved_code = self._extract_code_from_session(result)
            
            if improved_code:
                logger.info("✓ Jules generated improved scraper code")
                return improved_code
            else:
                logger.warning("⚠ Jules session completed but no code extracted")
                return None
                
        except JulesClientError as e:
            logger.error(f"✗ Jules session failed: {e}")
            return None
    
    def _extract_code_from_session(self, session: Dict[str, Any]) -> Optional[str]:
        """Extract code from Jules session outputs"""
        outputs = session.get("outputs", [])
        
        for output in outputs:
            if output.get("text"):
                text = output["text"]
                
                # Try to extract code block
                if "```python" in text:
                    start = text.find("```python") + 10
                    end = text.find("```", start)
                    if end > start:
                        return text[start:end].strip()
                
                # If no code block, return the text (might be pure code)
                return text.strip()
        
        return None
    
    def create_improvement_pr(
        self,
        site_name: str,
        improved_code: str,
        scraper_path: str,
        analysis_report: Dict[str, Any]
    ) -> Optional[str]:
        """
        Create a GitHub PR with the improved scraper.
        
        Args:
            site_name: Name of the site
            improved_code: Improved scraper code
            scraper_path: Path to scraper file in repository
            analysis_report: Analysis report for PR description
        
        Returns:
            PR URL if created, None otherwise
        """
        if not self.github_token:
            logger.warning("No GitHub token provided, skipping PR creation")
            return None
        
        # This would use GitHub API to create branch and PR
        # For now, return placeholder
        logger.info(f"Would create PR with improved scraper for {site_name}")
        logger.info(f"Improved code length: {len(improved_code)} characters")
        
        # Save improved code to file
        output_path = f"improved_{site_name.lower().replace(' ', '_')}_scraper.py"
        with open(output_path, "w") as f:
            f.write(improved_code)
        logger.info(f"Saved improved scraper to {output_path}")
        
        return None  # Placeholder - would return actual PR URL


def main():
    parser = argparse.ArgumentParser(description="Scraper Improvement Cycle")
    parser.add_argument("--site-name", required=True, help="Site name")
    parser.add_argument("--site-url", required=True, help="Site URL")
    parser.add_argument("--scraper-file", required=True, help="Path to current scraper file")
    parser.add_argument("--scraped-events", required=True, help="Path to scraped events JSON")
    parser.add_argument("--missed-events", required=True, help="Path to missed events JSON")
    parser.add_argument("--site-html", help="Path to saved site HTML (optional)")
    parser.add_argument("--agent-id", default="jules-1", help="Jules agent ID")
    parser.add_argument("--source-id", help="Jules source ID")
    parser.add_argument("--output", help="Output path for improved scraper")
    
    args = parser.parse_args()
    
    # Load environment
    if not os.environ.get("JULES_API_KEY"):
        print("Error: JULES_API_KEY not set")
        sys.exit(1)
    
    # Load data
    with open(args.scraped_events) as f:
        scraped_events = json.load(f)
    
    with open(args.missed_events) as f:
        missed_events = json.load(f)
    
    with open(args.scraper_file) as f:
        current_scraper_code = f.read()
    
    site_html = ""
    if args.site_html and os.path.exists(args.site_html):
        with open(args.site_html) as f:
            site_html = f.read()
    
    # Initialize improver
    improver = ScraperImprover(
        agent_id=args.agent_id,
        source_id=args.source_id,
        github_token=os.environ.get("GITHUB_TOKEN")
    )
    
    # Step 1: Analyze missed events
    print("\n1. Analyzing missed events...")
    analysis = improver.analyze_missed_events(
        scraped_events=scraped_events,
        missed_events=missed_events,
        site_html=site_html,
        site_url=args.site_url
    )
    
    print(json.dumps(analysis, indent=2))
    
    if not analysis.get("improvements_needed"):
        print("\n✓ No improvements needed!")
        sys.exit(0)
    
    # Step 2: Generate improved scraper with Jules
    print("\n2. Generating improved scraper with Jules AI...")
    improved_code = improver.generate_improvement_with_jules(
        site_name=args.site_name,
        site_url=args.site_url,
        current_scraper_code=current_scraper_code,
        missed_event_analysis=analysis,
        missed_events_sample=missed_events[:10]
    )
    
    if not improved_code:
        print("\n✗ Failed to generate improved scraper")
        sys.exit(1)
    
    # Step 3: Save or create PR
    print("\n3. Saving improved scraper...")
    
    output_path = args.output or f"improved_{args.site_name.lower().replace(' ', '_')}_scraper.py"
    with open(output_path, "w") as f:
        f.write(improved_code)
    
    print(f"✓ Improved scraper saved to {output_path}")
    
    # Step 4: Create PR (if GitHub token available)
    print("\n4. Creating GitHub PR...")
    pr_url = improver.create_improvement_pr(
        site_name=args.site_name,
        improved_code=improved_code,
        scraper_path=args.scraper_file,
        analysis_report=analysis
    )
    
    if pr_url:
        print(f"✓ PR created: {pr_url}")
    else:
        print("⚠ No PR created (check GitHub token or manual review needed)")
    
    print("\n" + "=" * 60)
    print("Improvement cycle complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
