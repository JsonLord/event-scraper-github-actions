import pytest
from unittest.mock import patch, MagicMock
from src.github_auth.permissions import get_token_scopes, check_permissions, PermissionChecker

@patch("requests.get")
def test_get_token_scopes_success(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"X-OAuth-Scopes": "repo, workflow"}
    mock_get.return_value = mock_response

    scopes = get_token_scopes("fake-token")
    assert "repo" in scopes
    assert "workflow" in scopes
    assert len(scopes) == 2

@patch("requests.get")
def test_get_token_scopes_failure(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_get.return_value = mock_response

    scopes = get_token_scopes("bad-token")
    assert scopes == []

def test_check_permissions():
    with patch("src.github_auth.permissions.get_token_scopes") as mock_scopes:
        mock_scopes.return_value = ["repo"]
        assert check_permissions("token", ["actions", "contents"]) is True

        mock_scopes.return_value = ["actions"]
        assert check_permissions("token", ["actions"]) is True
        assert check_permissions("token", ["repo"]) is False

def test_permission_checker():
    with patch("src.github_auth.permissions.get_token_scopes") as mock_scopes:
        mock_scopes.return_value = ["workflow"]
        checker = PermissionChecker("token")

        assert checker.has_permission("workflow") is True
        assert checker.has_permission("actions") is True # mapped in code
        assert checker.has_permission("repo") is False

        mock_scopes.return_value = ["repo"]
        checker = PermissionChecker("token")
        assert checker.has_permission("actions") is True
        assert checker.has_permission("anything") is True
