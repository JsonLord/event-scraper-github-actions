"""
Jules API Client for Event Scraper System

This module provides a Python client for interacting with the Jules API,
enabling automated coding sessions for event scraping tasks.
"""

import os
import json
from typing import Optional, Dict, Any, List

JULES_API_BASE = "https://jules.googleapis.com/v1alpha"


class JulesClientError(Exception):
    """Base exception for Jules client errors"""
    pass


class JulesClient:
    """
    Client for interacting with the Jules API.
    
    Supports multiple agents (jules-1 through jules-4) with separate API keys.
    """
    
    def __init__(self, agent_id: str = "jules-1"):
        """
        Initialize the Jules client.
        
        Args:
            agent_id: The agent ID to use (jules-1, jules-2, jules-3, or jules-4)
        """
        self.agent_id = agent_id
        self.api_key = self._get_api_key(agent_id)
        
        if not self.api_key:
            raise JulesClientError(
                f"No Jules API key found for agent {agent_id}. "
                f"Set JULES_API_KEY{'_' + agent_id.split('-')[1] if agent_id != 'jules-1' else ''} environment variable."
            )
    
    def _get_api_key(self, agent_id: str) -> Optional[str]:
        """Get Jules API key from environment based on agent_id"""
        if agent_id == "jules-1":
            return os.environ.get("JULES_API_KEY")
        else:
            key_var = f"JULES_API_KEY_{agent_id.split('-')[1]}"
            fallback = os.environ.get("JULES_API_KEY")
            return os.environ.get(key_var) or fallback
    
    def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make a request to the Jules API"""
        try:
            import requests
        except ImportError as e:
            raise JulesClientError(
                "The 'requests' package is required for Jules API calls. "
                "Install project dependencies with `pip install -r requirements.txt`."
            ) from e

        url = f"{JULES_API_BASE}/{endpoint}"
        headers = {
            "X-Goog-Api-Key": self.api_key,
            "Content-Type": "application/json"
        }
        
        if "headers" in kwargs:
            headers.update(kwargs.pop("headers"))
        
        try:
            response = requests.request(method, url, headers=headers, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise JulesClientError(f"Jules API request failed: {str(e)}")
    
    def list_sources(self) -> Dict[str, Any]:
        """
        List all available sources (GitHub repos connected to Jules).

        Returns:
            Dict containing list of sources
        """
        return self._make_request("GET", "sources")

    def find_source_for_repo(self, repo_full_name: str) -> Optional[str]:
        """
        Resolve the Jules source name for a GitHub repo.

        Args:
            repo_full_name: "owner/repo" (e.g. the GITHUB_REPOSITORY value
                GitHub Actions sets automatically).

        Returns:
            The source name (e.g. "sources/github/owner/repo") or None if no
            connected source matches.
        """
        if not repo_full_name:
            return None
        data = self.list_sources()
        sources = data.get("sources", []) if isinstance(data, dict) else []
        target = repo_full_name.strip().lower()
        for src in sources:
            if not isinstance(src, dict):
                continue
            name = src.get("name", "")
            gh = src.get("githubRepo") or src.get("gitHubRepo") or {}
            owner = gh.get("owner") or ""
            repo = gh.get("repo") or gh.get("repository") or ""
            gh_full = f"{owner}/{repo}".lower()
            # Match either the structured owner/repo or the source name, which
            # is formatted like "sources/github/owner/repo".
            if (owner and repo and target == gh_full) or (target and target in name.lower()):
                return name
        return None
    
    def create_session(
        self,
        prompt: str,
        title: Optional[str] = None,
        source_id: Optional[str] = None,
        branch: str = "main",
        automation_mode: str = "AUTO_CREATE_PR"
    ) -> Dict[str, Any]:
        """
        Create a new Jules session.
        
        Args:
            prompt: The task prompt for the agent
            title: Session title (optional)
            source_id: Jules source ID (e.g., "sources/github/owner/repo")
            branch: Starting branch (default: "main")
            automation_mode: Automation mode (default: "AUTO_CREATE_PR")
        
        Returns:
            Dict containing session details
        """
        payload = {
            "prompt": prompt,
            "automationMode": automation_mode,
            "title": title or f"Session {os.urandom(4).hex()}"
        }
        
        if source_id:
            payload["sourceContext"] = {
                "source": source_id,
                "githubRepoContext": {"startingBranch": branch}
            }
        
        return self._make_request("POST", "sessions", json=payload)
    
    def get_session(self, session_id: str) -> Dict[str, Any]:
        """
        Get session details including PR outputs.
        
        Args:
            session_id: The session ID (without "sessions/" prefix)
        
        Returns:
            Dict containing session details
        """
        return self._make_request("GET", f"sessions/{session_id}")
    
    def list_activities(
        self,
        session_id: str,
        page_size: int = 50
    ) -> Dict[str, Any]:
        """
        List activities for a session.
        
        Args:
            session_id: The session ID
            page_size: Number of activities to return (default: 50)
        
        Returns:
            Dict containing list of activities
        """
        return self._make_request(
            "GET",
            f"sessions/{session_id}/activities?pageSize={page_size}"
        )
    
    def send_message(self, session_id: str, message: str) -> Dict[str, Any]:
        """
        Send a message to an existing session.
        
        Args:
            session_id: The session ID
            message: The message content
        
        Returns:
            Dict containing response
        """
        return self._make_request(
            "POST",
            f"sessions/{session_id}:sendMessage",
            json={"prompt": message}
        )
    
    def wait_for_session(
        self,
        session_id: str,
        timeout: int = 3600,
        check_interval: int = 30
    ) -> Dict[str, Any]:
        """
        Wait for a session to complete and return final state.
        
        Args:
            session_id: The session ID
            timeout: Maximum wait time in seconds (default: 3600)
            check_interval: Time between checks in seconds (default: 30)
        
        Returns:
            Dict containing final session state
        """
        import time
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            session = self.get_session(session_id)
            state = session.get("state", "")
            
            if state == "COMPLETED":
                return session
            elif state == "FAILED":
                raise JulesClientError(f"Session failed: {session}")
            
            time.sleep(check_interval)
        
        raise JulesClientError(f"Session timeout after {timeout} seconds")
    
    def extract_pr_from_session(self, session: Dict[str, Any]) -> Optional[str]:
        """
        Extract PR URL from session outputs.
        
        Args:
            session: Session dict from get_session()
        
        Returns:
            PR URL if found, None otherwise
        """
        for output in session.get("outputs", []):
            pr = output.get("pullRequest", {})
            if pr.get("url"):
                return pr["url"]
        return None


# Convenience functions for simple usage
def list_sources(agent_id: str = "jules-1") -> Dict[str, Any]:
    """List available sources using default client"""
    client = JulesClient(agent_id)
    return client.list_sources()


def create_session(
    prompt: str,
    agent_id: str = "jules-1",
    **kwargs
) -> Dict[str, Any]:
    """Create a new session using default client"""
    client = JulesClient(agent_id)
    return client.create_session(prompt, **kwargs)


def get_session(session_id: str, agent_id: str = "jules-1") -> Dict[str, Any]:
    """Get session details using default client"""
    client = JulesClient(agent_id)
    return client.get_session(session_id)


def list_activities(
    session_id: str,
    agent_id: str = "jules-1",
    **kwargs
) -> Dict[str, Any]:
    """List activities using default client"""
    client = JulesClient(agent_id)
    return client.list_activities(session_id, **kwargs)


def send_message(
    session_id: str,
    message: str,
    agent_id: str = "jules-1"
) -> Dict[str, Any]:
    """Send message using default client"""
    client = JulesClient(agent_id)
    return client.send_message(session_id, message)


if __name__ == "__main__":
    # Example usage
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "list-sources":
        try:
            sources = list_sources()
            print(json.dumps(sources, indent=2))
        except JulesClientError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    elif len(sys.argv) > 1 and sys.argv[1] == "find-source":
        # Print ONLY the resolved source name to stdout (so it can be captured
        # in a shell $(...) ); diagnostics go to stderr. Defaults the repo to
        # the GITHUB_REPOSITORY env var that GitHub Actions provides.
        repo = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("GITHUB_REPOSITORY", "")
        try:
            source = JulesClient().find_source_for_repo(repo)
        except JulesClientError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        if source:
            print(source)
        else:
            print(f"No Jules source found for '{repo}'", file=sys.stderr)
            sys.exit(2)

    elif len(sys.argv) > 2 and sys.argv[1] == "create":
        prompt = " ".join(sys.argv[2:])
        try:
            session = create_session(prompt)
            print(f"Created session: {session.get('name')}")
            print(json.dumps(session, indent=2))
        except JulesClientError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    
    else:
        print("Usage:")
        print("  python jules_client.py list-sources")
        print("  python jules_client.py find-source [owner/repo]")
        print("  python jules_client.py create <prompt>")
