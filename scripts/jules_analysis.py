"""
Jules Completeness Analysis

Analyzes raw scraped data to identify missed events and patterns.
Uses Jules AI to understand why certain events were missed.

Workflow:
1. Load raw HTML and scraped events
2. Compare against expected event patterns
3. Use Jules to identify missed event patterns
4. Generate improvement recommendations
"""

import os
import sys
import json
import argparse
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from jules_client import JulesClient, JulesClientError

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class CompletenessAnalyzer:
    """
    Analyzes scraped results to find missed events using Jules AI.
    """
    
    def __init__(self, agent_id: str = "jules-1"):
        self.jules = JulesClient(agent_id)
    
    def analyze(
        self,
        source: str,
        raw_html: str,
        scraped_events: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Analyze completeness of scraped events.
        
        Args:
            source: Source name
            raw_html: Full HTML of the page
            scraped_events: Events that were successfully scraped
        
        Returns:
            Analysis results with missed patterns and recommendations
        """
        logger.info(f"Analyzing completeness for {source}...")
        
        # Step 1: Use Jules to analyze HTML and find missed events
        prompt = f"""
        ANALYZE EVENT SCRAPING COMPLETENESS
        
        Source: {source}
        
        CURRENTLY SCRAPED EVENTS ({len(scraped_events)} found):
        {json.dumps(scraped_events[:10], indent=2)}  # Show first 10
        
        FULL PAGE HTML (truncated for analysis):
        {raw_html[:50000]}  # First 50k chars
        
        TASK:
        1. Identify event patterns in the HTML that were NOT captured
        2. Explain WHY they were missed (wrong selectors, different structure, etc.)
        3. Identify the PATTERN of missed events (not just individual events)
        4. Provide specific improvement recommendations
        
        Look for:
        - Events in different containers (e.g., sidebar, modal, lazy-loaded)
        - Events with different HTML structure
        - Events with alternative date/price formats
        - Events in tabs, accordions, or pagination
        
        Return JSON with:
        {{
            "scraped_count": <number>,
            "estimated_total": <estimated total events on page>,
            "missed_count": <estimated missed>,
            "missed_patterns": [
                {{
                    "pattern_name": "e.g., 'sidebar_events'",
                    "description": "What type of events were missed",
                    "html_structure": "Describe the HTML structure",
                    "why_missed": "Why current scraper missed them",
                    "example": {{sample missed event data}}
                }}
            ],
            "needs_update": true/false,
            "improvement_recommendations": [
                "Specific code changes needed"
            ]
        }}
        """
        
        try:
            session = self.jules.create_session(
                prompt=prompt,
                title=f"Completeness Analysis: {source}",
                source_id=os.environ.get("JULES_SOURCE_ID"),
                branch="main"
            )
            
            session_id = session["name"].split("/")[-1]
            logger.info(f"Created analysis session: {session_id}")
            
            # Wait for completion
            result = self.jules.wait_for_session(session_id, timeout=1800)
            
            # Extract analysis
            analysis = self._extract_analysis(result)
            
            if analysis:
                logger.info(f"✓ Analysis complete: {analysis.get('missed_count', 0)} missed events found")
                return analysis
            else:
                logger.warning("⚠ Jules session completed but no analysis extracted")
                return self._default_analysis(scraped_events)
                
        except JulesClientError as e:
            logger.error(f"✗ Jules session failed: {e}")
            return self._default_analysis(scraped_events)
    
    def _extract_analysis(self, session: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract analysis from Jules session"""
        outputs = session.get("outputs", [])
        
        for output in outputs:
            if output.get("text"):
                text = output["text"]
                
                # Try to parse JSON
                try:
                    # Find JSON block
                    if "{" in text:
                        start = text.find("{")
                        # Find matching closing brace (simplified)
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
                
                # Try to extract code block
                if "```json" in text:
                    start = text.find("```json") + 8
                    end = text.find("```", start)
                    if end > start:
                        try:
                            return json.loads(text[start:end].strip())
                        except:
                            pass
        
        return None
    
    def _default_analysis(self, scraped_events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Return default analysis if Jules fails"""
        return {
            "scraped_count": len(scraped_events),
            "estimated_total": len(scraped_events),
            "missed_count": 0,
            "missed_patterns": [],
            "needs_update": False,
            "improvement_recommendations": []
        }


def main():
    parser = argparse.ArgumentParser(description="Jules Completeness Analysis")
    parser.add_argument("--source", required=True, help="Source name")
    parser.add_argument("--raw-events", required=True, help="Path to raw events JSON")
    parser.add_argument("--html", required=True, help="Path to HTML file")
    parser.add_argument("--output", required=True, help="Output path for analysis")
    parser.add_argument("--agent-id", default="jules-1", help="Jules agent ID")
    
    args = parser.parse_args()
    
    # Load environment
    if not os.environ.get("JULES_API_KEY"):
        print("Error: JULES_API_KEY not set")
        sys.exit(1)
    
    # Load data
    with open(args.raw_events) as f:
        raw_data = json.load(f)
        scraped_events = raw_data.get("events", [])
    
    with open(args.html) as f:
        raw_html = f.read()
    
    # Run analysis
    analyzer = CompletenessAnalyzer(agent_id=args.agent_id)
    analysis = analyzer.analyze(
        source=args.source,
        raw_html=raw_html,
        scraped_events=scraped_events
    )
    
    # Save results
    analysis["source"] = args.source
    analysis["analyzed_at"] = datetime.now().isoformat()
    
    with open(args.output, "w") as f:
        json.dump(analysis, f, indent=2)
    
    print(f"Analysis saved to {args.output}")
    print(f"Missed events: {analysis.get('missed_count', 0)}")
    print(f"Needs update: {analysis.get('needs_update', False)}")


if __name__ == "__main__":
    main()
