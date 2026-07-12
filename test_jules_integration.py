"""
Test script for Jules API + CloakBrowser integration

This script demonstrates the complete workflow:
1. List available sources
2. Create a session with a scraping task
3. Wait for completion
4. Extract PR URL
"""

import os
import sys
import json
from datetime import datetime

# Load environment variables from .env file
def load_env():
    """Load environment variables from .env file"""
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()

load_env()

# Add scripts directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'scripts'))

from jules_client import JulesClient, JulesClientError


def main():
    print("=" * 60)
    print("Jules API + Event Scraper Test")
    print("=" * 60)
    
    # Initialize client
    try:
        client = JulesClient("jules-1")
        print("✓ Jules client initialized")
    except JulesClientError as e:
        print(f"✗ Failed to initialize Jules client: {e}")
        sys.exit(1)
    
    # List sources
    print("\n1. Listing available sources...")
    try:
        sources = client.list_sources()
        source_list = sources.get("sources", [])
        print(f"✓ Found {len(source_list)} sources")
        
        # Show first few sources
        for source in source_list[:5]:
            repo = source.get("githubRepo", {})
            print(f"  - {repo.get('owner')}/{repo.get('repo')}")
        
        if len(source_list) > 5:
            print(f"  ... and {len(source_list) - 5} more")
        
    except JulesClientError as e:
        print(f"✗ Failed to list sources: {e}")
        sys.exit(1)
    
    # Create a test session
    print("\n2. Creating test session...")
    test_prompt = """
    Create a simple Python function that extracts event data from HTML.
    
    The function should:
    1. Accept HTML string and base URL as parameters
    2. Parse the HTML using BeautifulSoup
    3. Extract event title, date, time, price, venue, and description
    4. Return a list of dictionaries with keys: title, date, time, price, venue, description, url
    
    Keep it simple and focused on basic HTML parsing.
    """
    
    # Use first available source
    if source_list:
        source_id = source_list[0]["name"]
    else:
        print("✗ No sources available")
        sys.exit(1)
    
    try:
        session = client.create_session(
            prompt=test_prompt,
            title="Test: Event Extractor Function",
            source_id=source_id,
            branch="main"
        )
        
        session_id = session["name"].split("/")[-1]
        print(f"✓ Session created: {session_id}")
        print(f"  Title: {session.get('title')}")
        print(f"  State: {session.get('state')}")
        
    except JulesClientError as e:
        print(f"✗ Failed to create session: {e}")
        sys.exit(1)
    
    # Wait for completion (with timeout)
    print("\n3. Waiting for session completion (this may take 5-10 minutes)...")
    print("   Press Ctrl+C to cancel")
    
    import time
    start_time = time.time()
    timeout = 600  # 10 minutes
    
    try:
        while time.time() - start_time < timeout:
            session = client.get_session(session_id)
            state = session.get("state", "UNKNOWN")
            
            print(f"   Status: {state}...", end="\r")
            
            if state == "COMPLETED":
                print(f"\n✓ Session completed!")
                
                # Extract PR URL if available
                pr_url = client.extract_pr_from_session(session)
                if pr_url:
                    print(f"  PR created: {pr_url}")
                else:
                    print("  No PR created (session may have just generated code)")
                
                # Show outputs
                outputs = session.get("outputs", [])
                if outputs:
                    print(f"\n  Outputs ({len(outputs)} items):")
                    for i, output in enumerate(outputs[:3]):
                        if output.get("text"):
                            text = output["text"][:200] + "..." if len(output["text"]) > 200 else output["text"]
                            print(f"    [{i}] {text}")
                
                break
                
            elif state == "FAILED":
                print(f"\n✗ Session failed!")
                print(f"  Error: {session}")
                sys.exit(1)
            
            time.sleep(30)
            
    except KeyboardInterrupt:
        print(f"\n\n⚠ Cancelled by user")
        print(f"  Session {session_id} is still running")
        print(f"  Check Jules dashboard for status")
        sys.exit(0)
    
    if time.time() - start_time >= timeout:
        print(f"\n✗ Timeout after {timeout} seconds")
        print(f"  Session {session_id} may still be running")
        sys.exit(1)
    
    print("\n" + "=" * 60)
    print("Test completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()
