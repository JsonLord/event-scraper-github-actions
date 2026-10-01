import pytest
import responses
import zipfile
import io
from src.workflow_monitor import WorkflowMonitor
from src.github_auth.service import GitHubAuthService

def create_mock_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("logs/main.txt", "Main log content")
        z.writestr("logs/step1.txt", "Step 1 log content")
    buf.seek(0)
    return buf.read()

@responses.activate
def test_workflow_monitor_download_logs_integration():
    # Mocking GitHubAuthService
    from unittest.mock import MagicMock
    import requests

    auth_service = MagicMock(spec=GitHubAuthService)
    auth_service.authenticated_client.return_value = requests.Session()

    owner = "test-owner"
    repo = "test-repo"
    run_id = 999

    monitor = WorkflowMonitor(auth_service, owner, repo)

    zip_content = create_mock_zip()

    # Mock the log download endpoint
    responses.add(
        responses.GET,
        f"https://api.github.com/repos/{owner}/{repo}/actions/runs/{run_id}/logs",
        body=zip_content,
        status=200,
        content_type="application/zip"
    )

    # Call the new method in WorkflowMonitor
    logs = monitor.download_run_logs(run_id)

    # Verify the results
    assert len(logs) == 2
    assert logs["logs/main.txt"] == "Main log content"
    assert logs["logs/step1.txt"] == "Step 1 log content"

    # Verify that the correct URL was called
    assert len(responses.calls) == 1
    assert responses.calls[0].request.url == f"https://api.github.com/repos/{owner}/{repo}/actions/runs/{run_id}/logs"
