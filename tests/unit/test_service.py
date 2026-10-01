import pytest
import os
from unittest.mock import patch, MagicMock
from src.github_auth.service import GitHubAuthService

@pytest.fixture
def mock_cache():
    return MagicMock()

@patch.dict(os.environ, {"GITHUB_TOKEN": "env-token"})
@patch("src.github_auth.service.GitHubAuthService._validate_token")
def test_init_with_pat(mock_validate, mock_cache):
    mock_validate.return_value = True
    service = GitHubAuthService(cache=mock_cache)

    assert service._token == "env-token"
    mock_cache.set_token.assert_called_with("env-token", method="env")

@patch.dict(os.environ, {}, clear=True)
@patch("src.github_auth.service.GitHubAuthService._validate_token")
@patch("subprocess.run")
def test_init_with_gh_cli(mock_run, mock_validate, mock_cache):
    mock_validate.return_value = True
    mock_cache.get_token.return_value = None

    mock_run.return_value = MagicMock(returncode=0, stdout="gh-token\n")

    service = GitHubAuthService(cache=mock_cache)
    assert service._token == "gh-token"
    mock_cache.set_token.assert_called_with("gh-token", expiry_seconds=3600, method="gh")

@patch("requests.get")
def test_validate_token_success(mock_get, mock_cache):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_get.return_value = mock_response

    service = GitHubAuthService(cache=mock_cache)
    assert service._validate_token("valid") is True

@patch("requests.get")
def test_validate_token_failure(mock_get, mock_cache):
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_get.return_value = mock_response

    service = GitHubAuthService(cache=mock_cache)
    assert service._validate_token("invalid") is False

@patch("src.github_auth.service.GitHubAuthService.get_token")
def test_authenticated_client_headers(mock_get_token, mock_cache):
    mock_get_token.return_value = "secret-token"
    service = GitHubAuthService(cache=mock_cache)

    client = service.authenticated_client()
    assert client.headers["Authorization"] == "token secret-token"
