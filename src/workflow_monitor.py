import time
import logging
import requests
from typing import Optional, Dict, Any, Callable

logger = logging.getLogger(__name__)

class WorkflowMonitor:
    def __init__(self, auth_service, owner: str, repo: str):
        """
        Initialize the WorkflowMonitor.

        :param auth_service: An instance of GitHubAuthService.
        :param owner: The owner of the repository.
        :param repo: The name of the repository.
        """
        self.auth_service = auth_service
        self.owner = owner
        self.repo = repo
        self.base_url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs"

    def get_status(self, run_id: int) -> Dict[str, Any]:
        """
        Fetches the current status and conclusion of a workflow run.

        :param run_id: The ID of the workflow run.
        :return: A dictionary containing 'status' and 'conclusion'.
        :raises ValueError: If the workflow run is not found.
        :raises requests.exceptions.HTTPError: For other HTTP errors, including rate limits.
        """
        session = self.auth_service.authenticated_client()
        url = f"{self.base_url}/{run_id}"

        response = session.get(url)

        if response.status_code == 404:
            raise ValueError(f"Workflow run {run_id} not found.")

        # Handle rate limiting if raise_for_status is called
        if response.status_code in [403, 429]:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                logger.warning(f"Rate limited. Retry after {retry_after} seconds.")

        response.raise_for_status()

        data = response.json()
        return {
            "status": data.get("status"),
            "conclusion": data.get("conclusion")
        }

    def poll_until_complete(
        self,
        run_id: int,
        interval: int = 30,
        timeout: int = 300,
        on_state_change: Optional[Callable[[str, Optional[str]], None]] = None
    ) -> Dict[str, Any]:
        """
        Polls until the workflow run is completed.

        :param run_id: The ID of the workflow run.
        :param interval: Polling interval in seconds.
        :param timeout: Maximum wait time in seconds.
        :param on_state_change: Optional callback function(status, conclusion).
        :return: The final status and conclusion.
        :raises TimeoutError: If the workflow run does not complete within the timeout.
        """
        start_time = time.time()
        last_status = None

        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout:
                raise TimeoutError(f"Workflow run {run_id} did not complete within {timeout} seconds. Last status: {last_status}")

            try:
                result = self.get_status(run_id)
                current_status = result["status"]
                conclusion = result["conclusion"]

                if current_status != last_status:
                    if on_state_change:
                        on_state_change(current_status, conclusion)
                    last_status = current_status

                if current_status == "completed":
                    return result

            except requests.exceptions.HTTPError as e:
                if e.response is not None and e.response.status_code in [403, 429]:
                    retry_after_header = e.response.headers.get("Retry-After")
                    sleep_time = int(retry_after_header) if retry_after_header and retry_after_header.isdigit() else interval
                    logger.info(f"Rate limited during polling. Sleeping for {sleep_time} seconds.")
                    time.sleep(sleep_time)
                    # We don't advance the loop's sleep time if we hit a rate limit,
                    # but we should still check for timeout in the next iteration.
                    continue
                raise

            time.sleep(interval)
