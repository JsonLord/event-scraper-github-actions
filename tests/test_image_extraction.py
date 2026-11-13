"""Image extraction: structured metadata first, card markup last, never fatal.

Every case here is a shape a Berlin venue site actually emits. The theme is
that an image is *decoration*: it must be found where it is stated, must never
be invented, and must never be the reason an otherwise valid event is dropped.
"""

import sys
from types import ModuleType

sys.modules.setdefault("requests", ModuleType("requests"))

import pytest  # noqa: E402

pytest.importorskip("bs4")

from scripts.generic_event_scraper import (  # noqa: E402
    _image_from_detail_page,
    enrich_missing_images,
    extract_jsonld_events,
    extract_time_element_events,
)
from scripts.image_utils import (  # noqa: E402
    attach_image,
    best_document_image,
    card_image,
    check_image_url,
    jsonld_image,
    looks_decorative,
    meta_images,
    resolve_image_url,
)

SOURCE = "https://example.de/programm"


def _page(head: str = "", body: str = "") -> str:
    return f"<html><head>{head}</head><body>{body}</body></html>"


# --------------------------------------------------------------- JSON-LD ---

def test_jsonld_image_as_plain_url_string():
    html = _page(head='''<script type="application/ld+json">
      {"@type":"Event","name":"Kiez Konzert","startDate":"2026-09-19T20:00:00+02:00",
       "image":"https://example.de/poster.jpg"}
      </script>''')
    events = extract_jsonld_events(html, SOURCE)
    assert events[0]["image_url"] == "https://example.de/poster.jpg"
    assert events[0]["image_source"] == "jsonld_image"


def test_jsonld_image_as_array_of_urls():
    html = _page(head='''<script type="application/ld+json">
      {"@type":"Event","name":"Kiez Konzert","startDate":"2026-09-19",
       "image":["https://example.de/first.jpg","https://example.de/second.jpg"]}
      </script>''')
    events = extract_jsonld_events(html, SOURCE)
    assert events[0]["image_url"] == "https://example.de/first.jpg"


def test_jsonld_image_object_with_url():
    html = _page(head='''<script type="application/ld+json">
      {"@type":"Event","name":"Kiez Konzert","startDate":"2026-09-19",
       "image":{"@type":"ImageObject","url":"https://example.de/obj.jpg"}}
      </script>''')
    events = extract_jsonld_events(html, SOURCE)
    assert events[0]["image_url"] == "https://example.de/obj.jpg"


def test_jsonld_image_object_with_content_url():
    html = _page(head='''<script type="application/ld+json">
      {"@type":"Event","name":"Kiez Konzert","startDate":"2026-09-19",
       "image":{"@type":"ImageObject","contentUrl":"https://example.de/content.jpg"}}
      </script>''')
    events = extract_jsonld_events(html, SOURCE)
    assert events[0]["image_url"] == "https://example.de/content.jpg"


def test_jsonld_image_array_of_objects():
    node = {"image": [{"@type": "ImageObject", "url": "https://a.de/x.jpg"}]}
    assert jsonld_image(node) == "https://a.de/x.jpg"


def test_jsonld_relative_image_is_resolved_against_the_event_page():
    html = _page(head='''<script type="application/ld+json">
      {"@type":"Event","name":"Kiez Konzert","startDate":"2026-09-19",
       "url":"https://example.de/events/konzert",
       "image":"/media/poster.jpg"}
      </script>''')
    events = extract_jsonld_events(html, SOURCE)
    assert events[0]["image_url"] == "https://example.de/media/poster.jpg"


def test_jsonld_without_image_falls_back_to_the_page_preview():
    html = _page(
        head='''<meta property="og:image" content="https://example.de/og.jpg">
      <script type="application/ld+json">
      {"@type":"Event","name":"Kiez Konzert","startDate":"2026-09-19"}</script>''',
    )
    events = extract_jsonld_events(html, SOURCE)
    assert events[0]["image_url"] == "https://example.de/og.jpg"
    assert events[0]["image_source"] == "og_image"


# ----------------------------------------------------------- Open Graph ---

def test_open_graph_image_variants_are_read_in_priority_order():
    html = _page(head='''
      <meta property="og:image" content="https://example.de/plain.jpg">
      <meta property="og:image:secure_url" content="https://example.de/secure.jpg">''')
    entries = meta_images(html)
    assert entries[0] == {"url": "https://example.de/secure.jpg", "source": "og_image"}
    assert entries[1]["url"] == "https://example.de/plain.jpg"


def test_open_graph_read_from_name_attribute_too():
    """Several German venue sites emit name= instead of property=."""
    html = _page(head='<meta name="og:image" content="https://example.de/name.jpg">')
    assert best_document_image(html, SOURCE)["url"] == "https://example.de/name.jpg"


# --------------------------------------------------------------- Twitter ---

def test_twitter_image_is_read_when_open_graph_is_absent():
    html = _page(head='<meta name="twitter:image" content="https://example.de/tw.jpg">')
    found = best_document_image(html, SOURCE)
    assert found == {"url": "https://example.de/tw.jpg", "source": "twitter_image"}


def test_twitter_image_src_variant():
    html = _page(head='<meta name="twitter:image:src" content="https://example.de/twsrc.jpg">')
    assert best_document_image(html, SOURCE)["url"] == "https://example.de/twsrc.jpg"


def test_open_graph_beats_twitter():
    html = _page(head='''
      <meta name="twitter:image" content="https://example.de/tw.jpg">
      <meta property="og:image" content="https://example.de/og.jpg">''')
    assert best_document_image(html, SOURCE)["source"] == "og_image"


# ----------------------------------------------------------- relative URL ---

def test_relative_image_urls_are_resolved():
    assert resolve_image_url("/img/a.jpg", "https://example.de/x/y") == "https://example.de/img/a.jpg"
    assert resolve_image_url("img/a.jpg", "https://example.de/x/y") == "https://example.de/x/img/a.jpg"
    assert resolve_image_url("//cdn.example/a.jpg", "https://example.de/") == "https://cdn.example/a.jpg"


def test_unusable_image_urls_are_rejected():
    for raw in ("", "data:image/png;base64,AAA", "javascript:void(0)", "#", "mailto:x@y.z"):
        assert resolve_image_url(raw, "https://example.de/") == ""


# ---------------------------------------------------------------- cards ---

def test_lazy_loaded_card_image_is_found():
    """data-src is what a lazy-loading card carries instead of src."""
    html = _page(body='''
      <div class="event-card">
        <img data-src="/media/lazy.jpg" alt="Konzert Poster">
        <h3>Kiez Konzert</h3>
      </div>''')
    card = _page_soup(html).find("div", class_="event-card")
    assert card_image(card, SOURCE) == "https://example.de/media/lazy.jpg"


def test_srcset_prefers_the_largest_candidate():
    html = _page(body='''
      <div class="event-card">
        <img srcset="/media/small.jpg 320w, /media/large.jpg 1280w" alt="Poster">
      </div>''')
    card = _page_soup(html).find("div", class_="event-card")
    assert card_image(card, SOURCE) == "https://example.de/media/large.jpg"


def test_picture_source_is_used_when_img_has_nothing():
    html = _page(body='''
      <div class="event-card">
        <picture><source srcset="/media/avif.avif 2x"><img alt=""></picture>
      </div>''')
    card = _page_soup(html).find("div", class_="event-card")
    assert card_image(card, SOURCE) == "https://example.de/media/avif.avif"


def test_logo_and_avatar_are_not_taken_as_event_artwork():
    """A card often holds the site logo next to the artwork."""
    html = _page(body='''
      <div class="event-card">
        <img src="/static/logo.svg" alt="Example Berlin">
        <h3>Kiez Konzert</h3>
      </div>''')
    card = _page_soup(html).find("div", class_="event-card")
    assert card_image(card, SOURCE) == ""


def test_tracking_pixel_is_rejected():
    assert looks_decorative("https://www.google-analytics.com/collect?v=1") is True
    assert looks_decorative("https://example.de/pixel.gif", width="1", height="1") is True


def test_small_thumbnail_is_rejected_as_decorative():
    assert looks_decorative("https://example.de/a.png", width="32", height="32") is True
    assert looks_decorative("https://example.de/poster.jpg", width="1200", height="630") is False


def test_time_element_cards_carry_their_image():
    html = _page(body='''
      <article class="show">
        <time datetime="2026-09-19T20:00:00">19. Sept</time>
        <img data-original="/media/show.jpg" alt="Abendvorstellung">
        <h3>Abendvorstellung</h3>
        <a href="/veranstaltung/abend">Details</a>
      </article>''')
    events = extract_time_element_events(html, SOURCE)
    assert events and events[0]["image_url"] == "https://example.de/media/show.jpg"


# ------------------------------------------------------- missing/invalid ---

def test_page_with_no_image_yields_no_image_fields():
    html = _page(body="<div class='event-card'><h3>Kiez Konzert</h3></div>")
    card = _page_soup(html).find("div", class_="event-card")
    assert card_image(card, SOURCE) == ""


def test_attach_image_never_overwrites_a_stronger_source():
    event = {"image_url": "https://a.de/keep.jpg", "image_source": "jsonld_image"}
    attach_image(event, "https://a.de/new.jpg", "event_card_image", SOURCE)
    assert event["image_url"] == "https://a.de/keep.jpg"


def test_attach_image_is_a_no_op_on_junk():
    event = {}
    attach_image(event, "", "jsonld_image", SOURCE)
    assert "image_url" not in event
    attach_image(event, "/x.jpg", "jsonld_image", "")  # no base to resolve against
    assert "image_url" not in event


def test_detail_page_image_prefers_jsonld_then_open_graph():
    jsonld_html = _page(
        head='''<meta property="og:image" content="https://example.de/og.jpg">
        <script type="application/ld+json">
        {"@type":"Event","name":"X","startDate":"2026-09-19",
         "image":"https://example.de/ld.jpg"}</script>''')
    assert _image_from_detail_page(jsonld_html, SOURCE)["url"] == "https://example.de/ld.jpg"

    og_only = _page(head='<meta property="og:image" content="https://example.de/og.jpg">')
    assert _image_from_detail_page(og_only, SOURCE)["url"] == "https://example.de/og.jpg"

    assert _image_from_detail_page(_page(body="<p>nothing</p>"), SOURCE) is None


def test_image_enrichment_respects_its_own_fetch_budget():
    events = [
        {"title": f"E{i}", "image_url": None, "url": f"https://example.de/e{i}",
         "source_url": "https://example.de/list"} for i in range(5)
    ]
    fetched = []

    def fake_fetch(url):
        fetched.append(url)
        return _page(head='<meta property="og:image" content="/p.jpg">')

    enrich_missing_images(events, max_fetches=2, fetch=fake_fetch)
    assert len(fetched) == 2
    assert sum(1 for e in events if e["image_url"]) == 2


def test_image_enrichment_skips_events_that_already_have_one():
    events = [{"title": "E", "image_url": "https://a.de/x.jpg",
               "url": "https://example.de/e", "source_url": "https://example.de/list"}]
    enrich_missing_images(events, fetch=lambda url: pytest.fail("should not fetch"))


# ------------------------------------------------------- bounded HTTP check ---

class _FakeResponse:
    def __init__(self, status=200, content_type="image/jpeg", chunks=(b"x" * 512,), length=None):
        self.status_code = status
        self.headers = {"Content-Type": content_type}
        if length is not None:
            self.headers["Content-Length"] = str(length)
        self._chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_content(self, size):
        for chunk in self._chunks:
            yield chunk


class _FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_image_check_accepts_a_real_image():
    session = _FakeSession(_FakeResponse())
    outcome = check_image_url("https://example.de/p.jpg", session=session)
    assert outcome["ok"] is True
    assert outcome["content_type"] == "image/jpeg"


def test_image_check_rejects_non_image_content_types():
    session = _FakeSession(_FakeResponse(content_type="text/html"))
    outcome = check_image_url("https://example.de/p.jpg", session=session)
    assert outcome["ok"] is False
    assert outcome["reason"] == "not_an_image"


def test_image_check_rejects_an_oversized_image():
    session = _FakeSession(_FakeResponse(length=50 * 1024 * 1024))
    outcome = check_image_url("https://example.de/p.jpg", session=session)
    assert outcome["ok"] is False
    assert outcome["reason"] == "too_large"


def test_image_check_reports_http_errors_as_unverified():
    session = _FakeSession(_FakeResponse(status=404))
    assert check_image_url("https://example.de/p.jpg", session=session)["ok"] is False


def test_image_check_never_raises_on_a_transport_error():
    class Boom:
        def get(self, url, **kwargs):
            raise RuntimeError("connection reset")

    outcome = check_image_url("https://example.de/p.jpg", session=Boom())
    assert outcome["ok"] is False


def _page_soup(html: str):
    from bs4 import BeautifulSoup

    return BeautifulSoup(html, "lxml")
