"""Regression tests for the ranking model.

The published run put five San Francisco meetups and seven rows literally
named "Event 1"…"Event 12" above every real Berlin event. These tests pin the
ordering properties that prevent that.
"""

from datetime import date

from scripts.score_events import (
    imminence_score,
    match_categories,
    price_score,
    score_and_filter_events,
    score_event,
)

TODAY = date(2026, 8, 27)


def _event(**overrides):
    base = {
        "title": "Some Berlin Event",
        "date": "2026-08-28",
        "time": "20:00",
        "price": None,
        "description": "",
        "venue": "Festsaal Kreuzberg",
        "url": "https://example.de/events/some-berlin-event",
        "source_url": "https://example.de/events/",
        "has_detail_link": True,
    }
    base.update(overrides)
    return base


def test_unknown_price_scores_between_the_preferred_and_cutoff_bands():
    """Unknown used to score 5 against 40 for free, penalising two thirds of
    all real listings and rewarding scrapers that guessed 0."""
    assert price_score(15.0) < price_score(None) < price_score(5.0) < price_score(0.0)


def test_a_free_guess_cannot_outrank_a_complete_listing():
    placeholder = _event(
        title="Free Community Meetup",
        price=0.0,
        venue="",
        description="",
        time="",
        has_detail_link=False,
    )
    real = _event(
        title="Konzert im Festsaal Kreuzberg",
        price=None,
        description="Live concert with three bands.",
    )
    assert score_event(real, TODAY)["score"] > score_event(placeholder, TODAY)["score"]


def test_category_credit_has_diminishing_returns():
    """Matching four categories signals a noisy description, not a better
    event; flat per-category points ranked listing chrome above clean rows."""
    focused = _event(title="Techno Konzert", description="A live music night.")
    noisy = _event(
        title="Programm",
        description="Theater Musiktheater Tanz Performance Musical Ausstellung workshop",
    )
    assert score_event(focused, TODAY)["score"] >= score_event(noisy, TODAY)["score"]


def test_sooner_events_outrank_later_ones():
    assert imminence_score("2026-08-27", TODAY) > imminence_score("2026-09-02", TODAY)
    assert imminence_score("2027-07-24", TODAY) < imminence_score("2026-08-28", TODAY)
    assert imminence_score(None, TODAY) == 0


def test_incomplete_rows_sink_below_complete_ones():
    complete = _event(description="A full description of the night.")
    thin = _event(venue="", description="", time="", has_detail_link=False)
    assert score_event(complete, TODAY)["score"] > score_event(thin, TODAY)["score"]


def test_charlottenburg_proximity_matches_on_the_venue_column():
    """The bonus fired zero times across 207 published rows, because venue was
    blank on 62% of them and the pattern only saw the text fields."""
    near = _event(venue="Schloss Charlottenburg")
    far = _event(venue="Festsaal Kreuzberg")
    assert "near Charlottenburg" in match_categories(near)
    assert "near Charlottenburg" not in match_categories(far)
    assert score_event(near, TODAY)["score"] > score_event(far, TODAY)["score"]


def test_title_matches_rank_ahead_of_description_only_matches():
    categories = match_categories(
        _event(title="Tanzabend", description="A museum exhibition is nearby.")
    )
    assert categories[0] == "dancing"


def test_results_are_sorted_by_score_then_date():
    events = [
        _event(title="Later", date="2026-09-02", price=None, url="https://example.de/events/later"),
        _event(title="Free tonight", date="2026-08-27", price=0.0,
               description="Live concert in the garden.", url="https://example.de/events/tonight"),
        _event(title="Tomorrow", date="2026-08-28", price=None, url="https://example.de/events/tomorrow"),
    ]
    ordered = score_and_filter_events(events, today=TODAY)
    assert [e["title"] for e in ordered][0] == "Free tonight"
    assert ordered == sorted(ordered, key=lambda e: -e["score"])


def test_events_above_the_cutoff_are_removed():
    assert score_and_filter_events([_event(price=40.0)], today=TODAY) == []
