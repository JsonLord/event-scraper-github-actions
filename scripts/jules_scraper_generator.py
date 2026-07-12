"""
Jules Scraper Generator

Uses Jules AI to generate improved scraper scripts based on completeness analysis.

Input: Analysis JSON with missed event patterns
Output: Improved Python scraper code
"""

import os
import sys
import json
import argparse
import logging
from typing import Dict, Any, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from jules_client import JulesClient, JulesClientError

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class ScraperGenerator:
    """
    Generates improved scraper scripts using Jules AI.
    """
    
    def __init__(self, agent_id: str = "jules-1"):
        self.agent_id = agent_id
        self.jules = None

    def _get_jules(self) -> JulesClient:
        if self.jules is None:
            self.jules = JulesClient(self.agent_id)
        return self.jules
    
    def generate(
        self,
        source: str,
        analysis: Dict[str, Any],
        current_scraper_code: Optional[str] = None
    ) -> Optional[str]:
        """
        Generate improved scraper code.
        
        Args:
            source: Source name
            analysis: Completeness analysis from Jules
            current_scraper_code: Current scraper code (if exists)
        
        Returns:
            Improved scraper code, or None if generation failed
        """
        logger.info(f"Generating improved scraper for {source}...")
        
        # Build prompt
        missed_patterns = analysis.get("missed_patterns", [])
        recommendations = analysis.get("improvement_recommendations", [])
        
        prompt = f"""
        GENERATE IMPROVED EVENT SCRAPER
        
        Source: {source}
        
        COMPLETENESS ANALYSIS:
        - Scraped count: {analysis.get('scraped_count', 0)}
        - Missed count: {analysis.get('missed_count', 0)}
        - Needs update: {analysis.get('needs_update', False)}
        
        MISSED EVENT PATTERNS:
        {json.dumps(missed_patterns, indent=2)}
        
        IMPROVEMENT RECOMMENDATIONS:
        {json.dumps(recommendations, indent=2)}
        
        CURRENT SCRAPER CODE:
        ```python
        {current_scraper_code or "# No existing scraper - create from scratch"}
        ```
        
        TASK:
        Generate an IMPROVED Python scraper that:
        
        1. KEEPS all working selectors from the current code
        2. ADDS new selectors for missed event patterns
        3. HANDLES multiple HTML structures (grid, list, card layouts)
        4. PARSES alternative date/price formats
        5. EXTRACTS events from sidebars, modals, lazy-loaded content
        6. MAINTAINS price filtering (≤15€) and date range (14 days)
        7. RETURNS same event schema: title, date, time, price, category, description, url, venue, source_url
        
        IMPORTANT:
        - This is a GENERAL improvement, not just for specific events
        - The scraper should adapt to SIMILAR patterns in the future
        - Use BeautifulSoup for parsing
        - Include error handling for missing elements
        - Add comments explaining each selector's purpose
        
        Return ONLY the Python code, no explanations.
        """
        
        try:
            jules = self._get_jules()
            session = jules.create_session(
                prompt=prompt,
                title=f"Scraper Generator: {source}",
                source_id=os.environ.get("JULES_SOURCE_ID"),
                branch="main"
            )
            
            session_id = session["name"].split("/")[-1]
            logger.info(f"Created generation session: {session_id}")
            
            # Wait for completion
            result = jules.wait_for_session(session_id, timeout=1800)
            
            # Extract code
            code = self._extract_code(result)
            
            if code:
                logger.info(f"✓ Generated {len(code)} characters of scraper code")
                return code
            else:
                logger.warning("⚠ Jules session completed but no code extracted")
                return None
                
        except JulesClientError as e:
            logger.error(f"✗ Jules session failed: {e}")
            return None
    
    def _extract_code(self, session: Dict[str, Any]) -> Optional[str]:
        """Extract code from Jules session"""
        outputs = session.get("outputs", [])
        
        for output in outputs:
            if output.get("text"):
                text = output["text"]
                
                # Try to extract Python code block
                if "```python" in text:
                    start = text.find("```python") + 10
                    end = text.find("```", start)
                    if end > start:
                        return text[start:end].strip()
                
                # If no code block, check if it looks like Python code
                if "import" in text and "def " in text:
                    return text.strip()
        
        return None


def main():
    parser = argparse.ArgumentParser(description="Jules Scraper Generator")
    parser.add_argument("--source", required=True, help="Source name")
    parser.add_argument("--analysis", required=True, help="Path to analysis JSON")
    parser.add_argument("--output", required=True, help="Output path for scraper")
    parser.add_argument("--agent-id", default="jules-1", help="Jules agent ID")
    
    args = parser.parse_args()
    
    # Load environment
    if not os.environ.get("JULES_API_KEY"):
        print("Error: JULES_API_KEY not set")
        sys.exit(1)
    
    # Load analysis
    with open(args.analysis) as f:
        analysis = json.load(f)
    
    # Try to load current scraper
    current_code = None
    scraper_path = f"scripts/{args.source}_scraper.py"
    if os.path.exists(scraper_path):
        with open(scraper_path) as f:
            current_code = f.read()
    
    # Generate improved scraper
    generator = ScraperGenerator(agent_id=args.agent_id)
    code = generator.generate(
        source=args.source,
        analysis=analysis,
        current_scraper_code=current_code
    )
    
    if not code:
        print("✗ Failed to generate scraper")
        sys.exit(1)
    
    # Save to file
    with open(args.output, "w") as f:
        f.write(code)
    
    print(f"✓ Improved scraper saved to {args.output}")
    print(f"  Code length: {len(code)} characters")


if __name__ == "__main__":
    main()
