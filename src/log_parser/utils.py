import re
from typing import Optional

# Standard GitHub Actions log timestamp format: 2024-01-01T00:00:00.1234567Z
TIMESTAMP_REGEX = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)\s")

def parse_timestamp(line: str) -> Optional[str]:
    """
    Extracts the ISO 8601 timestamp from a log line.
    """
    match = TIMESTAMP_REGEX.match(line)
    if match:
        return match.group(1)
    return None

def clean_line(line: str) -> str:
    """
    Removes the timestamp and any leading/trailing whitespace from a log line.
    """
    return TIMESTAMP_REGEX.sub("", line).strip()

def strip_ansi(text: str) -> str:
    """
    Removes ANSI escape sequences from text.
    """
    ansi_escape = re.compile(r'(?:\x1B[@-_]|[\x80-\x9F])[0-?]*[ -/]*[@-~]')
    return ansi_escape.sub('', text)
