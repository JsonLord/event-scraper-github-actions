#!/usr/bin/env python3
"""
The "extra Jules API call" step in the weekly chain: once all sites have
been scraped and aggregated, this makes ONE Jules session call asking Jules
to write a Python scoring/categorization script for the gathered events,
then runs whatever code Jules returns against the real data.

Jules is asked to solve the exact spec implemented in scripts/score_events.py
(see that module's docstring for the full preference profile). That
deterministic implementation doubles as:
  - the prompt's spec-by-example (embedded as reference code Jules may keep,
    tweak, or rewrite), and
  - the fallback used if the Jules call fails, times out, or Jules has no
    API key configured - so docs/events_scored.json is always produced and
    a flaky/slow/unavailable Jules API never breaks the weekly pipeline.
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jules_client import JulesClient, JulesClientError
import score_events

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

SPEC_REFERENCE = Path(__file__).with_name("score_events.py").read_text(encoding="utf-8")

PROMPT_TEMPLATE = """
Write a single self-contained Python 3 script that scores, categorizes and
filters a list of scraped Berlin events according to this preference
profile:

- Hard filter: drop any event whose price is a number greater than {max_price}
  EUR. Keep events with no detected price (treat as unknown, not free).
- Price scoring: free (price == 0) is best, price <= 10 EUR is preferred,
  price <= {max_price} EUR is acceptable, unknown price is neutral.
- Categorize and score each event against these categories, matched via
  keywords in the title/description (an event can match more than one):
  dancing, music, outside events, entrepreneurial events, social gatherings,
  theater, culture, musical, participating workshops.
- Also score a "proximity to Charlottenburg" location bonus if the venue or
  description mentions Charlottenburg (Berlin) or immediately adjacent
  landmarks (e.g. Kurfürstendamm) - this is a location bonus, not a content
  category.
- Combine these into a single 0-100 "score" per event, then sort the events
  best-to-worst by score (ties broken by lower price, then title).
- For each event, prefer a script that avoids naive substring keyword
  matching that would misfire on unrelated words (for example "art" should
  not match inside the English word "Startup"), while still matching German
  compound words such as "Tanzabend" or "Musikfestival" against stems like
  "tanz"/"musik".

The script must:
- Read a JSON file given via --input (shape: {{"events": [...]}}, where each
  event is a dict with at least: title, description, venue, price (number or
  null), date, time, category, url, source_url).
- Write a JSON file given via --output (shape: {{"count": N, "events": [...]}})
  where each output event keeps its original fields plus: price_label
  (human string like "Free", "€8", or "Check site"), matched_categories
  (list of matched category names, including "near Charlottenburg" if
  applicable), category (comma-joined matched content categories, or
  "general" if none matched), and score (0-100 integer).
- Accept --max-price (float, default {max_price}).
- Have no dependencies beyond the Python standard library.

For reference, here is a working implementation of this exact spec you may
adapt, improve, or rewrite from scratch - just return the final code:

```python
{reference}
```

Return ONLY the final Python code for the script, no explanations, no
markdown fences.
"""


def extract_code_from_session(session: dict) -> str:
    for output in session.get("outputs", []) or []:
        text = output.get("text")
        if text and "def " in text:
            return text
    raise JulesClientError("Jules session produced no usable code output")


def strip_markdown_fences(code: str) -> str:
    code = code.strip()
    if code.startswith("```"):
        lines = code.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        code = "\n".join(lines)
    return code


def run_jules_scorer(input_path: str, output_path: str, max_price: float,
                      agent_id: str, source_id: str, timeout: int) -> bool:
    """Attempt the one Jules API call. Returns True on success."""
    try:
        client = JulesClient(agent_id)
    except JulesClientError as e:
        logger.warning(f"Jules unavailable, skipping to fallback: {e}")
        return False

    prompt = PROMPT_TEMPLATE.format(max_price=max_price, reference=SPEC_REFERENCE)

    try:
        session = client.create_session(
            prompt=prompt,
            title="Score and categorize weekly events",
            source_id=source_id,
        )
        session_id = session["name"].split("/")[-1]
        logger.info(f"Created Jules scoring session: {session_id}")

        result = client.wait_for_session(session_id, timeout=timeout)
        code = strip_markdown_fences(extract_code_from_session(result))
    except JulesClientError as e:
        logger.warning(f"Jules scoring session failed, using local fallback: {e}")
        return False

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tmp:
        tmp.write(code)
        tmp_path = tmp.name

    try:
        proc = subprocess.run(
            [sys.executable, tmp_path,
             "--input", input_path, "--output", output_path, "--max-price", str(max_price)],
            capture_output=True, text=True, timeout=120,
        )
        if proc.returncode != 0:
            logger.warning(f"Jules-generated scoring script failed: {proc.stderr[-2000:]}")
            return False
        if not os.path.exists(output_path):
            logger.warning("Jules-generated scoring script produced no output file")
            return False
        logger.info("Jules-generated scoring script ran successfully")
        return True
    except subprocess.TimeoutExpired:
        logger.warning("Jules-generated scoring script timed out")
        return False
    finally:
        os.unlink(tmp_path)


def main():
    parser = argparse.ArgumentParser(description="Score events via one Jules API call, with a deterministic fallback")
    parser.add_argument("--input", required=True, help="Aggregated events JSON file")
    parser.add_argument("--output", required=True, help="Output scored events JSON file")
    parser.add_argument("--max-price", type=float, default=15.0)
    parser.add_argument("--agent-id", default="jules-1")
    parser.add_argument("--source-id", default=os.environ.get("JULES_SOURCE_ID"))
    parser.add_argument("--timeout", type=int, default=900, help="Max seconds to wait for the Jules session")
    parser.add_argument("--skip-jules", action="store_true", help="Go straight to the local fallback")
    args = parser.parse_args()

    used_jules = False
    if not args.skip_jules and os.environ.get("JULES_API_KEY"):
        used_jules = run_jules_scorer(
            args.input, args.output, args.max_price,
            args.agent_id, args.source_id, args.timeout,
        )
    else:
        logger.info("Skipping Jules call (no JULES_API_KEY or --skip-jules set)")

    if not used_jules:
        logger.info("Falling back to the local deterministic scorer")
        with open(args.input, encoding="utf-8") as f:
            data = json.load(f)
        events = data.get("events", data if isinstance(data, list) else [])
        scored = score_events.score_and_filter_events(events, args.max_price)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump({"count": len(scored), "events": scored}, f, indent=2, ensure_ascii=False)

    print(f"Done ({'Jules' if used_jules else 'local fallback'}) -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
