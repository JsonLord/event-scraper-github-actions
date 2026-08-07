import sys
from types import ModuleType


# Parsing tests do not make HTTP requests; keep them runnable in the minimal
# test environment where the optional scraper runtime dependencies are absent.
sys.modules.setdefault("requests", ModuleType("requests"))

from scripts.eventbrite_scraper import clean_event_title, extract_markdown_event


def test_linked_image_uses_event_page_and_cleans_image_metadata():
    line = (
        "[![Image 23: Hauptbild für Vernissage der Ausstellung ''Hellenic Heads'' "
        "von Georgios Petridis](https://img.evbuc.com/example)]"
        "(https://www.eventbrite.de/e/hellenic-heads-tickets-1992812061521)"
    )

    title, url = extract_markdown_event(line, "https://www.eventbrite.de/events")

    assert title == "Vernissage der Ausstellung ''Hellenic Heads'' von Georgios Petridis"
    assert url == "https://www.eventbrite.de/e/hellenic-heads-tickets-1992812061521"


def test_clean_event_title_accepts_english_main_image_label():
    assert clean_event_title("Image 4: Main image for Summer Meetup") == "Summer Meetup"
