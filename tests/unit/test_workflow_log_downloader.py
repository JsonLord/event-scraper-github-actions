import pytest
import responses
import zipfile
import io
import os
from unittest.mock import MagicMock
from src.workflow_log_downloader import WorkflowLogDownloader

@pytest.fixture
def auth_service_mock():
    mock = MagicMock()
    mock.authenticated_client.return_value = MagicMock()
    return mock

@pytest.fixture
def downloader(auth_service_mock):
    return WorkflowLogDownloader(auth_service_mock, "owner", "repo")

def create_mock_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("job1.txt", "Log content for job 1")
        z.writestr("job2.txt", "Log content for job 2")
        z.writestr("dir/job3.txt", "Log content for job 3")
    buf.seek(0)
    return buf.read()

@responses.activate
def test_download_logs_success(downloader):
    run_id = 123
    zip_content = create_mock_zip()

    responses.add(
        responses.GET,
        f"https://api.github.com/repos/owner/repo/actions/runs/{run_id}/logs",
        body=zip_content,
        status=200,
        content_type="application/zip"
    )

    import requests
    real_session = requests.Session()
    downloader.auth_service.authenticated_client.return_value = real_session

    logs = downloader.download_logs(run_id)

    assert len(logs) == 3
    assert logs["job1.txt"] == "Log content for job 1"
    assert logs["job2.txt"] == "Log content for job 2"
    assert logs["dir/job3.txt"] == "Log content for job 3"

@responses.activate
def test_download_logs_retry_on_429(downloader):
    run_id = 123
    zip_content = create_mock_zip()

    # First request fails with 429
    responses.add(
        responses.GET,
        f"https://api.github.com/repos/owner/repo/actions/runs/{run_id}/logs",
        status=429,
        headers={"Retry-After": "1"}
    )
    # Second request succeeds
    responses.add(
        responses.GET,
        f"https://api.github.com/repos/owner/repo/actions/runs/{run_id}/logs",
        body=zip_content,
        status=200
    )

    # We need to configure the session in the mock to actually use the adapter
    # But WorkflowLogDownloader._get_authenticated_session() already does that.
    # However, downloader.auth_service.authenticated_client.return_value needs to be a real session
    # if we want it to use the retries we mounted, OR we rely on responses to handle it.
    # Actually, responses doesn't automatically retry.
    # But since we are testing WorkflowLogDownloader, we want to see if it handles retries.

    # Wait, WorkflowLogDownloader uses urllib3 Retry through requests HTTPAdapter.
    # responses works by mocking the requests engine.

    import requests
    real_session = requests.Session()
    downloader.auth_service.authenticated_client.return_value = real_session

    logs = downloader.download_logs(run_id)

    assert len(logs) == 3
    assert len(responses.calls) == 2

@responses.activate
def test_download_logs_fail_after_retries(downloader):
    run_id = 123

    for _ in range(4):
        responses.add(
            responses.GET,
            f"https://api.github.com/repos/owner/repo/actions/runs/{run_id}/logs",
            status=500
        )

    import requests
    real_session = requests.Session()
    downloader.auth_service.authenticated_client.return_value = real_session

    with pytest.raises(requests.exceptions.RetryError):
        downloader.download_logs(run_id)

@responses.activate
def test_download_logs_404(downloader):
    run_id = 123

    responses.add(
        responses.GET,
        f"https://api.github.com/repos/owner/repo/actions/runs/{run_id}/logs",
        status=404
    )

    import requests
    real_session = requests.Session()
    downloader.auth_service.authenticated_client.return_value = real_session

    with pytest.raises(requests.exceptions.HTTPError) as excinfo:
        downloader.download_logs(run_id)
    assert excinfo.value.response.status_code == 404

@responses.activate
def test_download_logs_invalid_zip(downloader):
    run_id = 123

    responses.add(
        responses.GET,
        f"https://api.github.com/repos/owner/repo/actions/runs/{run_id}/logs",
        body=b"not a zip file",
        status=200
    )

    import requests
    real_session = requests.Session()
    downloader.auth_service.authenticated_client.return_value = real_session

    with pytest.raises(zipfile.BadZipFile):
        downloader.download_logs(run_id)
