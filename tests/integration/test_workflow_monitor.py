import pytest
import requests
from unittest.mock import MagicMock, patch
from src.workflow_monitor import WorkflowMonitor
from src.github_auth.service import GitHubAuthService

@pytest.fixture
def auth_service():
    service = MagicMock(spec=GitHubAuthService)
    session = MagicMock(spec=requests.Session)
    service.authenticated_client.return_value = session
    return service

@pytest.fixture
def monitor(auth_service):
    return WorkflowMonitor(auth_service, "test-owner", "test-repo")

@patch("time.sleep", return_value=None)
def test_full_polling_integration(mock_sleep, monitor, auth_service):
    session = auth_service.authenticated_client()

    # Mock sequence of GitHub API responses
    r1 = MagicMock()
    r1.status_code = 200
    r1.json.return_value = {"status": "queued", "conclusion": None}

    r2 = MagicMock()
    r2.status_code = 200
    r2.json.return_value = {"status": "in_progress", "conclusion": None}

    r3 = MagicMock()
    r3.status_code = 200
    r3.json.return_value = {"status": "completed", "conclusion": "success"}

    session.get.side_effect = [r1, r2, r3]

    states = []
    def callback(status, conclusion):
        states.append((status, conclusion))

    result = monitor.poll_until_complete(456, interval=1, on_state_change=callback)

    assert result["status"] == "completed"
    assert result["conclusion"] == "success"
    assert states == [
        ("queued", None),
        ("in_progress", None),
        ("completed", "success")
    ]
    assert session.get.call_count == 3

@patch("time.sleep", return_value=None)
def test_polling_with_failure_integration(mock_sleep, monitor, auth_service):
    session = auth_service.authenticated_client()

    r1 = MagicMock()
    r1.status_code = 200
    r1.json.return_value = {"status": "in_progress", "conclusion": None}

    r2 = MagicMock()
    r2.status_code = 200
    r2.json.return_value = {"status": "completed", "conclusion": "failure"}

    session.get.side_effect = [r1, r2]

    result = monitor.poll_until_complete(789, interval=1)

    assert result["status"] == "completed"
    assert result["conclusion"] == "failure"
    assert session.get.call_count == 2
