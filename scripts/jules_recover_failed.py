#!/usr/bin/env python3
"""
The "extra Jules API call" step in the weekly chain: after all sites have
been scraped, this makes ONE Jules session call to recover events from the
sites whose scrape came back empty (0 events) - typically the hard cases the
generic scraper can't crack on its own (Cloudflare challenges, JS-only single
page apps, unusual markup).

Each scrape leg saves an HTML snapshot at data/html/<name>.html, so Jules is
handed the failed sites' URLs plus those snapshots and asked to extract events
from them and return structured JSON. Whatever it returns is merged back into
the aggregated event set before scoring.

This is best-effort and never fatal: if Jules has no API key, times out, or
returns nothing usable, the pipeline continues with the events that were
already scraped (the file at --output is left containing exactly the input
events). That keeps a flaky/slow/unavailable Jules API from breaking the
weekly run, while still using the session for the highest-value task when it
is available.
"""

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jules_client import JulesClient, JulesClientError

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Keep the prompt bounded: cap how many failed sites and how much HTML per
# site we send to Jules in a single session.
MAX_SITES = 12
MAX_HTML_CHARS = 12000

EVENT_SCHEMA_KEYS = ("title", "date", "time", "price", "category",
                     "description", "url", "venue", "source_url")

PROMPT_HEADER = """
You are recovering event listings from Berlin venue/event websites whose
automated scrape returned zero events. For each site below you are given its
URL and an HTML snapshot (which may be truncated, or may be a bot-challenge
page - if a snapshot is unusable, fetch the URL yourself if you can).

Extract the individual upcoming events from each site. For every event return
an object with these keys (use null when a value is genuinely unavailable):
  title, date (YYYY-MM-DD if possible), time (HH:MM 24h if possible),
  price (a number in EUR, 0 for free, or null if unknown),
  category, description, url (link to the specific event if available),
  venue, source_url (the site URL it came from).

Return ONLY a JSON array of these event objects - no explanation, no markdown
fences. If you cannot extract anything for a site, just omit it.

Sites:
"""


def find_failed_sites(raw_dir: str, html_dir: str) -> List[Tuple[str, str, str]]:
    """Return (name, source_url, html_path) for each raw_*.json with 0 events."""
    failed = []
    for raw_path in sorted(Path(raw_dir).glob("raw_*.json")):
        try:
            data = json.loads(raw_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        events = data.get("events", [])
        if events:
            continue  # site produced results; nothing to recover
        name = raw_path.stem[len("raw_"):]
        source_url = data.get("source", "")
        html_path = os.path.join(html_dir, f"{name}.html")
        failed.append((name, source_url, html_path))
    return failed


def build_prompt(failed_sites: List[Tuple[str, str, str]]) -> str:
    parts = [PROMPT_HEADER]
    for name, url, html_path in failed_sites[:MAX_SITES]:
        snippet = ""
        if os.path.exists(html_path):
            try:
                snippet = Path(html_path).read_text(encoding="utf-8", errors="ignore")[:MAX_HTML_CHARS]
            except OSError:
                snippet = ""
        parts.append(f"\n### Site: {name}\nURL: {url}\nHTML snapshot:\n{snippet}\n")
    return "".join(parts)


def extract_json_array(text: str) -> List[Dict[str, Any]]:
    """Pull the first JSON array of event objects out of Jules' output text."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r'^```[a-zA-Z]*\n?', '', text)
        text = re.sub(r'\n?```$', '', text).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            raise
        parsed = json.loads(text[start:end + 1])
    if isinstance(parsed, dict):
        parsed = parsed.get("events", [])
    if not isinstance(parsed, list):
        raise ValueError("Jules output was not a JSON array of events")
    return parsed


def normalize_event(raw: Dict[str, Any], fallback_source: str) -> Dict[str, Any]:
    event = {key: raw.get(key) for key in EVENT_SCHEMA_KEYS}
    event["title"] = (event.get("title") or "Untitled event")
    event["source_url"] = event.get("source_url") or fallback_source
    event["url"] = event.get("url") or event["source_url"]
    if not event.get("category"):
        event["category"] = ""
    return event


def recover_with_jules(failed_sites, agent_id, source_id, timeout) -> List[Dict[str, Any]]:
    try:
        client = JulesClient(agent_id)
    except JulesClientError as e:
        logger.warning(f"Jules unavailable, skipping recovery: {e}")
        return []

    # If no source id was supplied, resolve it at runtime from the repo Jules
    # is connected to (GITHUB_REPOSITORY is set automatically in Actions).
    if not source_id:
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        try:
            source_id = client.find_source_for_repo(repo)
            if source_id:
                logger.info(f"Resolved Jules source for {repo}: {source_id}")
            else:
                logger.info(f"No Jules source matched {repo!r}; proceeding without repo context")
        except JulesClientError as e:
            logger.warning(f"Could not resolve Jules source: {e}")

    prompt = build_prompt(failed_sites)
    try:
        session = client.create_session(
            prompt=prompt,
            title="Recover events from failed scrapes",
            source_id=source_id,
        )
        session_id = session["name"].split("/")[-1]
        logger.info(f"Created Jules recovery session: {session_id}")
        result = client.wait_for_session(session_id, timeout=timeout)
    except JulesClientError as e:
        logger.warning(f"Jules recovery session failed: {e}")
        return []

    text = ""
    for output in result.get("outputs", []) or []:
        if output.get("text"):
            text = output["text"]
            break
    if not text:
        logger.warning("Jules recovery session produced no text output")
        return []

    try:
        raw_events = extract_json_array(text)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Could not parse Jules recovery output as JSON: {e}")
        return []

    known_urls = {u for _, u, _ in failed_sites}
    default_source = next(iter(known_urls), "")
    recovered = [normalize_event(e, default_source) for e in raw_events if isinstance(e, dict)]
    logger.info(f"Jules recovered {len(recovered)} events from failed sites")
    return recovered


def merge_events(existing: List[Dict[str, Any]], recovered: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = {(str(e.get("title", "")).strip().lower(), str(e.get("date", "")).strip())
            for e in existing}
    merged = list(existing)
    for event in recovered:
        key = (str(event.get("title", "")).strip().lower(), str(event.get("date", "")).strip())
        if key in seen:
            continue
        seen.add(key)
        merged.append(event)
    return merged


def main():
    parser = argparse.ArgumentParser(description="Recover events from failed scrapes via one Jules API call")
    parser.add_argument("--aggregated", required=True, help="Aggregated events JSON (input)")
    parser.add_argument("--raw-dir", default="data", help="Directory with raw_<name>.json scrape outputs")
    parser.add_argument("--html-dir", default="data/html", help="Directory with <name>.html snapshots")
    parser.add_argument("--output", required=True, help="Output JSON file (aggregated + recovered events)")
    parser.add_argument("--agent-id", default="jules-1")
    parser.add_argument("--source-id", default=os.environ.get("JULES_SOURCE_ID"))
    parser.add_argument("--timeout", type=int, default=900, help="Max seconds to wait for the Jules session")
    parser.add_argument("--skip-jules", action="store_true", help="Skip the Jules call entirely")
    args = parser.parse_args()

    with open(args.aggregated, encoding="utf-8") as f:
        agg = json.load(f)
    existing = agg.get("events", agg if isinstance(agg, list) else [])

    failed_sites = find_failed_sites(args.raw_dir, args.html_dir)
    logger.info(f"{len(failed_sites)} site(s) returned 0 events and are candidates for recovery")

    recovered = []
    if failed_sites and not args.skip_jules and os.environ.get("JULES_API_KEY"):
        recovered = recover_with_jules(failed_sites, args.agent_id, args.source_id, args.timeout)
    elif not failed_sites:
        logger.info("No failed sites - nothing for Jules to recover")
    else:
        logger.info("Skipping Jules recovery (no JULES_API_KEY or --skip-jules set)")

    merged = merge_events(existing, recovered)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump({"events": merged, "count": len(merged),
                   "recovered_count": len(recovered)}, f, indent=2, ensure_ascii=False)

    print(f"Recovery done: {len(existing)} scraped + {len(recovered)} recovered = {len(merged)} total -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
