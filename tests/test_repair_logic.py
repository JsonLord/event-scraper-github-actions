import pytest
import os
import json
import subprocess
from unittest.mock import MagicMock, patch
from scripts.autonomous_repair import AutonomousRepair

@pytest.fixture
def repair():
    return AutonomousRepair(max_retries=2)

def test_run_scraper_success(repair, tmp_path):
    # Setup mock success
    script = tmp_path / "mock_scraper.py"
    output = tmp_path / "output.json"
    html = tmp_path / "site.html"

    with open(output, 'w') as f:
        json.dump({"event_count": 5, "events": [{"title": "Test", "price": 10}]}, f)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0

        success = repair.run_scraper(str(script), "http://test.com", str(output), str(html))
        assert success is True

def test_run_scraper_fail_zero_events(repair, tmp_path):
    script = tmp_path / "mock_scraper.py"
    output = tmp_path / "output.json"
    html = tmp_path / "site.html"

    with open(output, 'w') as f:
        json.dump({"event_count": 0, "events": []}, f)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0

        success = repair.run_scraper(str(script), "http://test.com", str(output), str(html))
        assert success is False

@patch("scripts.autonomous_repair.CompletenessAnalyzer.analyze")
@patch("scripts.autonomous_repair.ScraperGenerator.generate")
def test_repair_cycle_triggers_jules(mock_gen, mock_analyze, repair, tmp_path):
    script = tmp_path / "mock_scraper.py"
    script.write_text("old code")

    output = "data/raw_test.json"
    html = "data/html/test.html"
    os.makedirs("data/html", exist_ok=True)
    with open(html, 'w') as f: f.write("<html></html>")

    # First run fails (mock_run in run_scraper)
    # Second run succeeds
    with patch.object(AutonomousRepair, "run_scraper") as mock_run_scraper:
        mock_run_scraper.side_effect = [False, True]

        mock_analyze.return_value = {"needs_update": True, "missed_count": 5}
        mock_gen.return_value = "new improved code"

        success = repair.repair_cycle(str(script), "http://test.com", "test")

        assert success is True
        assert mock_analyze.called
        assert mock_gen.called
        assert script.read_text() == "new improved code"
