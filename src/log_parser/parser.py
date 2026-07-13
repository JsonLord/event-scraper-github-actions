from typing import List, Dict, Optional
from .utils import parse_timestamp, clean_line
from .extractors import extract_exit_code, extract_tracebacks, extract_error_messages

def parse_log(log_text: str) -> Dict:
    """
    Parses raw GitHub Actions log text into a structured tree.
    """
    lines = log_text.splitlines()

    # In GitHub Actions, logs often correspond to a single job if downloaded per run/job.
    # But let's assume we might have multiple jobs or just one main job.
    # Standard format: ##[group]Step Name

    jobs = []
    # For simplicity, if we don't see job markers, we treat everything as one job.
    current_job = {
        "name": "default-job",
        "id": "default-id",
        "timestamp": None,
        "status": "success",
        "steps": []
    }
    jobs.append(current_job)

    current_step = None
    step_lines = []

    for line in lines:
        timestamp = parse_timestamp(line)
        cleaned = clean_line(line)

        if not current_job["timestamp"] and timestamp:
            current_job["timestamp"] = timestamp

        if "##[group]" in line:
            # New step starts
            if current_step:
                # Close previous step
                finalize_step(current_step, step_lines)
                current_job["steps"].append(current_step)

            step_name = cleaned.replace("##[group]", "").strip()
            current_step = {
                "name": step_name,
                "number": len(current_job["steps"]) + 1,
                "timestamp": timestamp,
                "status": "success",
                "exit_code": None,
                "error_messages": [],
                "tracebacks": []
            }
            step_lines = []
        elif "##[endgroup]" in line:
            if current_step:
                finalize_step(current_step, step_lines)
                current_job["steps"].append(current_step)
                current_step = None
                step_lines = []
        else:
            if current_step:
                step_lines.append(line)
            else:
                # Lines outside of any group - could be job level or just ignored
                pass

    if current_step:
        finalize_step(current_step, step_lines)
        current_job["steps"].append(current_step)

    # Determine job status based on steps
    if any(step["status"] == "failure" for step in current_job["steps"]):
        current_job["status"] = "failure"

    return {"jobs": jobs}

def finalize_step(step: Dict, lines: List[str]):
    """
    Analyzes gathered lines for a step to extract metadata.
    """
    step["error_messages"] = extract_error_messages(lines)
    step["tracebacks"] = extract_tracebacks(lines)

    for line in lines:
        exit_code = extract_exit_code(line)
        if exit_code is not None:
            step["exit_code"] = exit_code
            if exit_code != 0:
                step["status"] = "failure"

    # If there are error messages or tracebacks but no exit code yet,
    # it might still be a failure if GitHub didn't report it explicitly in the process call
    if step["error_messages"] or step["tracebacks"]:
        if step["exit_code"] is None or step["exit_code"] != 0:
             # Heuristic: if we see errors, it's likely a failure unless status is already set
             if step["status"] == "success":
                  # We should be careful here, but usually errors mean failure
                  # However, GitHub Actions might continue on error.
                  # For now, let's trust the exit code or explicit failure markers if we find them.
                  pass

    # Re-check status if exit_code is not present but errors are
    if any("failed with exit code" in msg for msg in step["error_messages"]):
         step["status"] = "failure"
