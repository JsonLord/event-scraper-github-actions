import pytest
import requests
from unittest.mock import MagicMock, patch
from src.workflow_monitor import WorkflowMonitor

@pytest.fixture
def mock_auth_service():
    service = MagicMock()
    service.authenticated_client.return_value = MagicMock(spec=requests.Session)
    return service

@pytest.fixture
def monitor(mock_auth_service):
    return WorkflowMonitor(mock_auth_service, "owner", "repo")

def test_get_status_success(monitor, mock_auth_service):
    session = mock_auth_service.authenticated_client()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"status": "in_progress", "conclusion": None}
    session.get.return_value = mock_response

    status = monitor.get_status(123)
    assert status == {"status": "in_progress", "conclusion": None}
    session.get.assert_called_with("https://api.github.com/repos/owner/repo/actions/runs/123")

def test_get_status_not_found(monitor, mock_auth_service):
    session = mock_auth_service.authenticated_client()
    mock_response = MagicMock()
    mock_response.status_code = 404
    session.get.return_value = mock_response

    with pytest.raises(ValueError, match="Workflow run 123 not found"):
        monitor.get_status(123)

def test_get_status_rate_limit(monitor, mock_auth_service):
    session = mock_auth_service.authenticated_client()
    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_response.headers = {"Retry-After": "60"}
    mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_response)
    session.get.return_value = mock_response

    with pytest.raises(requests.exceptions.HTTPError):
        monitor.get_status(123)

@patch("time.sleep", return_value=None)
def test_poll_until_complete_success(mock_sleep, monitor):
    with patch.object(monitor, 'get_status') as mock_get_status:
        mock_get_status.side_effect = [
            {"status": "queued", "conclusion": None},
            {"status": "in_progress", "conclusion": None},
            {"status": "completed", "conclusion": "success"}
        ]

        on_state_change = MagicMock()
        result = monitor.poll_until_complete(123, interval=1, on_state_change=on_state_change)

        assert result == {"status": "completed", "conclusion": "success"}
        assert on_state_change.call_count == 3
        on_state_change.assert_any_call("queued", None)
        on_state_change.assert_any_call("in_progress", None)
        on_state_change.assert_any_call("completed", "success")

@patch("time.sleep", return_value=None)
@patch("time.time")
def test_poll_until_complete_timeout(mock_time, mock_sleep, monitor):
    # Mock time to simulate timeout
    mock_time.side_effect = [0, 301]

    with patch.object(monitor, 'get_status') as mock_get_status:
        mock_get_status.return_value = {"status": "in_progress", "conclusion": None}

        with pytest.raises(TimeoutError, match="did not complete within 300 seconds"):
            monitor.poll_until_complete(123, timeout=300)

@patch("time.sleep", return_value=None)
def test_poll_until_complete_rate_limit_retry(mock_sleep, monitor):
    with patch.object(monitor, 'get_status') as mock_get_status:
        # First call fails with rate limit, second succeeds
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.headers = {"Retry-After": "1"}
        rate_limit_error = requests.exceptions.HTTPError(response=mock_response)

        mock_get_status.side_effect = [
            rate_limit_error,
            {"status": "completed", "conclusion": "failure"}
        ]

        result = monitor.poll_until_complete(123, interval=1)
        assert result == {"status": "completed", "conclusion": "failure"}
        assert mock_get_status.call_count == 2
        mock_sleep.assert_called_with(1)
