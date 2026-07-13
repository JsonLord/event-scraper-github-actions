import re
from typing import List, Optional, Dict
from .utils import clean_line

# Regex to match exit code from GitHub Actions error messages
# Example: ##[error]The process '/usr/bin/python' failed with exit code 1
EXIT_CODE_REGEX = re.compile(r"failed with exit code (\d+)")

# Regex for Python traceback frames
# Example:   File "path/to/file.py", line 42, in function_name
TRACEBACK_FRAME_REGEX = re.compile(r'File "(.+)", line (\d+), in (.+)')

def extract_exit_code(line: str) -> Optional[int]:
    """
    Extracts the exit code from a log line if present.
    """
    cleaned = clean_line(line)
    match = EXIT_CODE_REGEX.search(cleaned)
    if match:
        return int(match.group(1))
    return None

def extract_tracebacks(lines: List[str]) -> List[Dict]:
    """
    Extracts Python tracebacks from a list of log lines.
    Returns a list of structured traceback frames as per spec.
    """
    traceback_frames = []

    i = 0
    while i < len(lines):
        line = clean_line(lines[i])

        if line.startswith("Traceback (most recent call last):"):
            current_traceback_frames = []
            i += 1
            # Parse frames
            while i < len(lines):
                line = clean_line(lines[i])
                frame_match = TRACEBACK_FRAME_REGEX.search(line)
                if frame_match:
                    frame = {
                        "file": frame_match.group(1),
                        "line": int(frame_match.group(2)),
                        "function": frame_match.group(3),
                        "code": "",
                        "message": ""
                    }
                    i += 1
                    # Check for code line (it's the line after the File line)
                    if i < len(lines):
                        code_line = clean_line(lines[i])
                        # If it doesn't look like another frame or an error message start
                        if not TRACEBACK_FRAME_REGEX.search(code_line) and not (":" in code_line and not code_line.startswith(" ")):
                             frame["code"] = code_line
                             i += 1
                    current_traceback_frames.append(frame)
                elif current_traceback_frames:
                    # Likely the error message at the end: "ValueError: Something went wrong"
                    error_message = line
                    for f in current_traceback_frames:
                        f["message"] = error_message
                    traceback_frames.extend(current_traceback_frames)
                    current_traceback_frames = []
                    break
                else:
                    # Malformed traceback
                    break
        else:
            i += 1

    return traceback_frames

def extract_error_messages(lines: List[str]) -> List[str]:
    """
    Extracts explicit error messages from log lines (prefixed with ##[error]).
    """
    errors = []
    for line in lines:
        raw_cleaned = line.strip()
        if "##[error]" in raw_cleaned:
            msg = clean_line(line).replace("##[error]", "").strip()
            if msg:
                errors.append(msg)
    return errors
