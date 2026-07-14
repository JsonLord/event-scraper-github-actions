import logging
import zipfile
import os
import tempfile
import argparse
from typing import Dict
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

class WorkflowLogDownloader:
    def __init__(self, auth_service, owner: str, repo: str):
        """
        Initialize the WorkflowLogDownloader.

        :param auth_service: An instance of GitHubAuthService.
        :param owner: The owner of the repository.
        :param repo: The name of the repository.
        """
        self.auth_service = auth_service
        self.owner = owner
        self.repo = repo
        self.base_url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs"

    def _get_authenticated_session(self) -> requests.Session:
        session = self.auth_service.authenticated_client()

        # Implement robust retry logic: exponential backoff, up to 3 retries
        # Retry on 429 (Rate Limit) and 5xx (Server Errors)
        retry_strategy = Retry(
            total=3,
            backoff_factor=1, # 1, 2, 4 seconds
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        return session

    def download_logs(self, run_id: int) -> Dict[str, str]:
        """
        Downloads workflow run logs as a zip archive, decompresses it,
        and returns individual log file contents.

        :param run_id: The ID of the workflow run.
        :return: A dictionary mapping filenames to their contents.
        :raises requests.exceptions.RequestException: For network/HTTP errors.
        :raises zipfile.BadZipFile: If the downloaded file is not a valid zip.
        """
        url = f"{self.base_url}/{run_id}/logs"
        session = self._get_authenticated_session()

        try:
            logger.info(f"Downloading logs for workflow run {run_id} from {url}")
            response = session.get(url, stream=True)
            response.raise_for_status()

            # GitHub API for logs returns a redirect to a zip file.
            # requests follows redirects by default.

            with tempfile.TemporaryDirectory() as temp_dir:
                zip_path = os.path.join(temp_dir, "logs.zip")
                with open(zip_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)

                log_contents = {}
                with zipfile.ZipFile(zip_path, "r") as z:
                    for filename in z.namelist():
                        # Skip directories in the zip
                        if filename.endswith('/'):
                            continue

                        with z.open(filename) as f:
                            # Extract and return individual log file contents as structured data
                            log_contents[filename] = f.read().decode("utf-8", errors="replace")

                logger.info(f"Successfully extracted {len(log_contents)} log files for run {run_id}")
                return log_contents

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to download logs for run {run_id}: {e}")
            raise
        except zipfile.BadZipFile as e:
            logger.error(f"Downloaded file for run {run_id} is not a valid zip archive: {e}")
            raise
        except Exception as e:
            logger.error(f"An unexpected error occurred while processing logs for run {run_id}: {e}")
            raise

def main():
    parser = argparse.ArgumentParser(description="Download GitHub Actions workflow run logs.")
    parser.add_argument("run_id", type=int, help="The ID of the workflow run.")
    parser.add_argument("--owner", required=True, help="The owner of the repository.")
    parser.add_argument("--repo", required=True, help="The name of the repository.")

    args = parser.parse_args()

    # Delayed import to avoid circular dependencies if any
    try:
        from src.github_auth.service import GitHubAuthService
    except ImportError:
        print("Error: GitHubAuthService not found. Make sure you are running from the project root.")
        exit(1)

    auth_service = GitHubAuthService()
    downloader = WorkflowLogDownloader(auth_service, args.owner, args.repo)

    try:
        logs = downloader.download_logs(args.run_id)
        print(f"Successfully downloaded {len(logs)} log files.")
        for filename in sorted(logs.keys()):
            print(f"- {filename} ({len(logs[filename])} bytes)")
    except Exception as e:
        print(f"Error: {e}")
        exit(1)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    main()
