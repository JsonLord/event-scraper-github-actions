from typing import List, Optional
import requests

def get_token_scopes(token: str) -> List[str]:
    """
    Fetches the scopes associated with a GitHub token.
    GitHub returns scopes in the 'X-OAuth-Scopes' header of API responses.
    """
    try:
        response = requests.get(
            "https://api.github.com/user",
            headers={"Authorization": f"token {token}"},
            timeout=10
        )
        if response.status_code == 200:
            scopes_header = response.headers.get("X-OAuth-Scopes", "")
            if scopes_header:
                return [s.strip() for s in scopes_header.split(",") if s.strip()]
        return []
    except requests.RequestException:
        return []

def check_permissions(token: str, required_scopes: List[str]) -> bool:
    """
    Checks if the token has all the required scopes.
    Note: Some scopes imply others, but for simplicity we check for exact matches
    or the 'repo' scope which covers most repo-related actions.
    """
    scopes = get_token_scopes(token)
    if not scopes:
        return False

    # 'repo' scope is a super-scope for many things
    if "repo" in scopes:
        return True

    for scope in required_scopes:
        if scope not in scopes:
            return False
    return True

class PermissionChecker:
    def __init__(self, token: str):
        self.token = token
        self._scopes: Optional[List[str]] = None

    @property
    def scopes(self) -> List[str]:
        if self._scopes is None:
            self._scopes = get_token_scopes(self.token)
        return self._scopes

    def has_permission(self, scope: str) -> bool:
        if not self.scopes:
            return False

        if "repo" in self.scopes:
            return True

        # Specific mappings if needed
        # e.g. 'actions' might require 'repo' or 'workflow'
        if scope == "actions" and "workflow" in self.scopes:
            return True

        return scope in self.scopes
