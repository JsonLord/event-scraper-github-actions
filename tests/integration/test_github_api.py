import pytest
import os
from src.github_auth.service import GitHubAuthService

@pytest.mark.skipif(not os.environ.get("GITHUB_TOKEN"), reason="GITHUB_TOKEN not set")
def test_list_repos_with_valid_token():
    service = GitHubAuthService()
    client = service.authenticated_client()

    response = client.get("https://api.github.com/user/repos")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

@pytest.mark.skipif(not os.environ.get("GITHUB_TOKEN"), reason="GITHUB_TOKEN not set")
def test_check_actions_permission():
    service = GitHubAuthService()
    # This might be true or false depending on the token, but it shouldn't crash
    result = service.has_permission("actions")
    assert isinstance(result, bool)

def test_refresh_pat_fails_gracefully(tmp_path):
    # Setup a cache with a PAT that is about to expire
    from src.github_auth.cache import AuthCache
    cache_file = tmp_path / "cache.json"
    cache = AuthCache(cache_file=cache_file)
    cache.set_token("fake-pat", expiry_seconds=10, method="env")

    with patch.dict(os.environ, {"GITHUB_TOKEN": "invalid-pat"}):
        service = GitHubAuthService(cache=cache)
        # It should try to initialize/refresh and fail gracefully (token will be None)
        assert service.get_token() is None

from unittest.mock import patch
