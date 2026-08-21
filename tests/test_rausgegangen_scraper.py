import sys
from types import ModuleType


sys.modules.setdefault("requests", ModuleType("requests"))

from scripts.rausgegangen_scraper import extract_events_from_markdown


def test_extracts_event_when_card_metadata_is_on_separate_lines():
    markdown = """
Friday, 21 August
19:30
from 12,50 €
[Open Air Cinema](https://rausgegangen.de/en/events/open-air-cinema-0/)
Freiluftkino Kreuzberg
"""

    events = extract_events_from_markdown(markdown, "https://rausgegangen.de/en/berlin/")

    assert len(events) == 1
    assert events[0]["title"] == "Open Air Cinema"
    assert events[0]["time"] == "19:30"
    assert events[0]["price"] == 12.5
    assert events[0]["url"].endswith("/events/open-air-cinema-0/")


def test_deduplicates_repeated_card_links():
    card = "[Community Meetup](https://rausgegangen.de/events/community-meetup/)"

    events = extract_events_from_markdown(f"Free\n{card}\n{card}", "https://rausgegangen.de/")

    assert len(events) == 1
    assert events[0]["price"] == 0.0
