import pytest
from src.log_parser.parser import parse_log
from src.log_parser.utils import parse_timestamp, clean_line
from src.log_parser.extractors import extract_exit_code, extract_tracebacks

def test_parse_timestamp():
    line = "2024-01-01T00:00:00.1234567Z ##[group]Run scraper"
    assert parse_timestamp(line) == "2024-01-01T00:00:00.1234567Z"

    line_no_ts = "Starting scraper..."
    assert parse_timestamp(line_no_ts) is None

def test_clean_line():
    line = "2024-01-01T00:00:00.1234567Z Starting scraper..."
    assert clean_line(line) == "Starting scraper..."

def test_extract_exit_code():
    line = "##[error]The process '/usr/bin/python' failed with exit code 1"
    assert extract_exit_code(line) == 1

    line_no_code = "Process finished successfully"
    assert extract_exit_code(line_no_code) is None

def test_extract_tracebacks():
    lines = [
        "2024-01-01T00:00:02Z Traceback (most recent call last):",
        "2024-01-01T00:00:02Z   File \"src/scrapers/rausgegangen.py\", line 42, in scrape",
        "2024-01-01T00:00:02Z     result = self.get_data()",
        "2024-01-01T00:00:02Z   File \"src/scrapers/rausgegangen.py\", line 15, in get_data",
        "2024-01-01T00:00:02Z     raise ValueError(\"Invalid response format\")",
        "2024-01-01T00:00:02Z ValueError: Invalid response format"
    ]
    tracebacks = extract_tracebacks(lines)
    assert len(tracebacks) == 2
    assert tracebacks[0]["message"] == "ValueError: Invalid response format"
    assert tracebacks[0]["function"] == "scrape"
    assert tracebacks[0]["line"] == 42
    assert tracebacks[1]["code"] == "raise ValueError(\"Invalid response format\")"
    assert tracebacks[1]["message"] == "ValueError: Invalid response format"

def test_parse_log_basic():
    log_text = """2024-01-01T00:00:00Z ##[group]Step 1
2024-01-01T00:00:01Z Hello World
2024-01-01T00:00:02Z ##[endgroup]"""
    result = parse_log(log_text)
    assert len(result["jobs"]) == 1
    job = result["jobs"][0]
    assert len(job["steps"]) == 1
    assert job["steps"][0]["name"] == "Step 1"
    assert job["steps"][0]["status"] == "success"

def test_parse_log_failure():
    with open("tests/fixtures/sample_log.txt", "r") as f:
        log_text = f.read()

    result = parse_log(log_text)
    job = result["jobs"][0]
    assert job["status"] == "failure"
    assert job["steps"][0]["status"] == "failure"
    assert job["steps"][0]["exit_code"] == 1
    assert len(job["steps"][0]["tracebacks"]) == 2 # 2 frames now
    assert job["steps"][1]["status"] == "success"

def test_empty_log():
    result = parse_log("")
    assert len(result["jobs"]) == 1
    assert len(result["jobs"][0]["steps"]) == 0

def test_malformed_lines():
    log_text = "Not a standard log line\nAnother weird line"
    result = parse_log(log_text)
    assert len(result["jobs"]) == 1
    assert result["jobs"][0]["status"] == "success"
