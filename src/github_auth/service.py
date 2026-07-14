import os
import logging
import requests
import subprocess
from typing import Optional, Dict, Any
from .cache import AuthCache
from .permissions import PermissionChecker

logger = logging.getLogger(__name__)

class GitHubAuthService:
    def __init__(self, cache: Optional[AuthCache] = None):
        self.cache = cache or AuthCache()
        self._token: Optional[str] = None
        self._permission_checker: Optional[PermissionChecker] = None
        self._initialize_token()

    def _initialize_token(self):
        # 1. Try environment variable
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            if self._validate_token(token):
                self._token = token
                self._permission_checker = PermissionChecker(token)
                self.cache.set_token(token, method="env")
                return

        # 2. Try cache
        token = self.cache.get_token()
        if token:
            if self._validate_token(token):
                self._token = token
                self._permission_checker = PermissionChecker(token)
                return
            else:
                self.cache.clear()

        # 3. Try gh CLI
        token = self._get_token_from_gh_cli()
        if token:
            if self._validate_token(token):
                self._token = token
                self._permission_checker = PermissionChecker(token)
                # gh CLI tokens usually don't expire quickly, but let's cache it for 1 hour
                self.cache.set_token(token, expiry_seconds=3600, method="gh")
                return

    def _get_token_from_gh_cli(self) -> Optional[str]:
        try:
            result = subprocess.run(
                ["gh", "auth", "token"],
                capture_output=True,
                text=True,
                check=False
            )
            if result.returncode == 0:
                return result.stdout.strip()

            # Fallback to gh api user if gh auth token fails (older versions or different config)
            result = subprocess.run(
                ["gh", "api", "user", "--silent"],
                capture_output=True,
                check=False
            )
            if result.returncode == 0:
                # If this succeeds, gh is authenticated.
                # But gh api doesn't easily give the token itself.
                # Usually 'gh auth token' is what we want.
                pass
        except FileNotFoundError:
            # gh CLI not installed
            pass
        return None

    def _validate_token(self, token: str) -> bool:
        if not token:
            return False
        try:
            response = requests.get(
                "https://api.github.com/user",
                headers={"Authorization": f"token {token}"},
                timeout=10
            )
            return response.status_code == 200
        except requests.RequestException:
            return False

    def get_token(self) -> Optional[str]:
        if not self._token or self._is_token_stale():
            self.refresh_token()
        return self._token

    def _is_token_stale(self) -> bool:
        return self.cache.is_near_expiry()

    def refresh_token(self):
        # If we have a cache, see how it was obtained
        method = "unknown"
        if self.cache._memory_cache:
            method = self.cache._memory_cache.get("method", "unknown")

        if method == "gh":
            try:
                subprocess.run(["gh", "auth", "refresh"], check=False)
            except FileNotFoundError:
                logger.warning("gh CLI not found during refresh")

        self._initialize_token()

        if not self._token:
            if method == "env":
                logger.warning("GITHUB_TOKEN environment variable is invalid or expired.")
            else:
                logger.warning("Failed to refresh GitHub token.")

    def authenticated_client(self) -> requests.Session:
        token = self.get_token()
        session = requests.Session()
        if token:
            session.headers.update({"Authorization": f"token {token}"})
        return session

    def has_permission(self, scope: str) -> bool:
        token = self.get_token()
        if not token:
            return False
        if not self._permission_checker or self._permission_checker.token != token:
            self._permission_checker = PermissionChecker(token)
        return self._permission_checker.has_permission(scope)
