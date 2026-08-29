"""Regression tests for the ranking model.

The published run put five San Francisco meetups and seven rows literally
named "Event 1"…"Event 12" above every real Berlin event. These tests pin the
ordering properties that prevent that.
"""

from datetime import date

from scripts.score_events import (
    CATEGORY_WEIGHTS,
    MAX_PRICE,
    category_weight,
    exclusion_reason,
    favorite_source_score,
    participation_score,
    timing_score,
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


def test_results_are_grouped_by_day_then_priced_free_first():
    """The published order is an agenda: earliest day first, and inside each
    day free events, then ascending by price, with unstated prices last."""
    events = [
        _event(title="Day2 ten", date="2026-08-30", price=10.0, url="https://example.de/events/d2-ten"),
        _event(title="Day1 unknown", date="2026-08-29", price=None, url="https://example.de/events/d1-unknown"),
        _event(title="Day1 free", date="2026-08-29", price=0.0, url="https://example.de/events/d1-free"),
        _event(title="Day2 free", date="2026-08-30", price=0.0, url="https://example.de/events/d2-free"),
        _event(title="Day1 twelve", date="2026-08-29", price=12.0, url="https://example.de/events/d1-twelve"),
    ]
    ordered = [e["title"] for e in score_and_filter_events(events, today=TODAY)]
    assert ordered == [
        "Day1 free", "Day1 twelve", "Day1 unknown",
        "Day2 free", "Day2 ten",
    ]


def test_unknown_price_sorts_after_every_known_price_within_a_day():
    events = [
        _event(title="Unknown", date="2026-08-29", price=None, url="https://example.de/events/u"),
        _event(title="Dearest", date="2026-08-29", price=19.5, url="https://example.de/events/d"),
    ]
    ordered = [e["title"] for e in score_and_filter_events(events, today=TODAY)]
    assert ordered == ["Dearest", "Unknown"]


def test_events_above_the_cutoff_are_removed():
    assert score_and_filter_events([_event(price=40.0)], today=TODAY) == []


def test_the_cutoff_is_twenty_euro():
    """Raised from 15: a 20 EUR ticket is kept, 20.01 is not."""
    assert MAX_PRICE == 20.0
    assert len(score_and_filter_events([_event(price=20.0)], today=TODAY)) == 1
    assert score_and_filter_events([_event(price=20.01)], today=TODAY) == []


def test_price_bands_stay_monotonic_up_to_the_new_cutoff():
    assert price_score(20.0) < price_score(15.0) < price_score(10.0) < price_score(0.0)
    assert price_score(20.0) < price_score(None) < price_score(10.0)
    assert price_score(25.0) == 0


# --------------------------------------------------------------------------
# Weighted categories and separate tables
# --------------------------------------------------------------------------

def test_category_weights_follow_the_stated_order():
    """Confirmed: dancing 20 > music 18 > culture 12, workshops and free
    guided tours 15."""
    assert CATEGORY_WEIGHTS["dancing"] == 20
    assert CATEGORY_WEIGHTS["music"] == 18
    assert CATEGORY_WEIGHTS["participating workshops"] == 15
    assert CATEGORY_WEIGHTS["guided tours"] == 15
    assert CATEGORY_WEIGHTS["culture"] == 12
    assert (CATEGORY_WEIGHTS["dancing"] > CATEGORY_WEIGHTS["music"]
            > CATEGORY_WEIGHTS["participating workshops"] > CATEGORY_WEIGHTS["culture"])


def test_a_dance_event_outscores_an_equivalent_culture_event():
    dance = _event(title="Tanzabend im Festsaal", price=0.0, url="https://example.de/events/tanz")
    culture = _event(title="Ausstellung im Museum", price=0.0, url="https://example.de/events/aus")
    assert score_event(dance, TODAY)["score"] > score_event(culture, TODAY)["score"]


def test_a_free_guided_tour_outscores_a_paid_one():
    free_tour = _event(title="Führung durch die Ausstellung", price=0.0,
                       url="https://example.de/events/f1")
    paid_tour = _event(title="Führung durch die Ausstellung", price=12.0,
                       url="https://example.de/events/f2")
    assert category_weight("guided tours", 0.0) == 15
    assert category_weight("guided tours", 12.0) == 6
    assert score_event(free_tour, TODAY)["score"] > score_event(paid_tour, TODAY)["score"]


def test_sport_and_networking_route_to_their_own_tables():
    run = _event(title="Sunday Run Club Tempelhof", url="https://example.de/events/run")
    net = _event(title="Founder Networking Breakfast", url="https://example.de/events/net")
    opera = _event(title="Die Zauberflöte", url="https://example.de/events/opera")
    assert score_event(run, TODAY)["stream"] == "sport"
    assert score_event(net, TODAY)["stream"] == "network"
    assert score_event(opera, TODAY)["stream"] == "main"


def test_a_dance_class_is_not_filed_under_sport():
    """'Hip Hop Dance Workout' matches both; dancing is the stronger stated
    preference, so it stays in the main table."""
    ev = _event(title="Hip Hop Dance Workout", url="https://example.de/events/hh")
    assert score_event(ev, TODAY)["stream"] == "main"


def test_a_comedy_show_is_not_filed_under_networking():
    """'Bad 4 Business' matched the bare keyword 'business'."""
    ev = _event(title="English Comedy: Bad 4 Business", url="https://example.de/events/c")
    assert score_event(ev, TODAY)["stream"] == "main"


# --------------------------------------------------------------------------
# Participation: taking part vs sitting and watching
# --------------------------------------------------------------------------

def test_a_festival_outscores_the_same_art_form_as_a_performance():
    """Calibration's clearest signal: an opera *festival* rated correct while
    an opera *performance* rated much too high, and a ballet *opening
    festival* was the only event rated too low."""
    festival = _event(title="Eröffnungsfest Staatsballett Berlin",
                      url="https://example.de/events/fest")
    performance = _event(title="Vorstellung: Giselle", url="https://example.de/events/vorst")
    assert score_event(festival, TODAY)["score"] > score_event(performance, TODAY)["score"]


def test_watching_is_penalised_and_joining_is_not():
    assert participation_score(_event(title="Lesung mit dem Autor")) < 0
    assert participation_score(_event(title="Vernissage und Gala")) < 0
    assert participation_score(_event(title="Sommerfest im Garten")) > 0
    assert participation_score(_event(title="Speed Friending Stammtisch")) > 0


def test_a_guided_tour_is_penalised_less_than_a_performance():
    tour = participation_score(_event(title="Führung durch die Ausstellung"))
    show = participation_score(_event(title="Revue: Die grosse Show"))
    assert show < tour < 0


def test_paid_comedy_is_penalised_but_cheap_comedy_is_not():
    """'Paid improv or comedy shows score very low' - but a €4 show rated
    about right, so the penalty starts above the near-free band."""
    assert participation_score(_event(title="Stand-up Comedy Night", price=15.0)) < 0
    assert participation_score(_event(title="Stand-up Comedy Night", price=4.0)) == 0
    assert participation_score(_event(title="Improv Open Mic", price=0.0)) == 0


def test_protest_is_not_treated_as_a_social_gathering():
    assert participation_score(_event(title="Protest Picknick am Kanzleramt")) < 0


# --------------------------------------------------------------------------
# Hard exclusions
# --------------------------------------------------------------------------

def test_kids_film_and_retail_events_are_excluded_entirely():
    for title, reason in [
        ("Daumenkino Kinderprogramm", "kids"),
        ("Fantasy Filmfest: Screening", "film"),
        ("TASCHEN Sale im Store", "retail"),
    ]:
        assert exclusion_reason(_event(title=title)) == reason
    assert exclusion_reason(_event(title="Tanzabend im Festsaal")) is None


def test_an_adults_only_note_is_not_read_as_family_programming():
    """A guided tour was excluded because it says it is *not* suitable for
    children - the keyword matched a negation."""
    assert exclusion_reason(_event(
        title="Führung durch die Ausstellung",
        description="The guided tour is in German and is not suitable for children under 14.",
    )) is None


def test_excluded_events_do_not_reach_the_output():
    events = [
        _event(title="Kinderprogramm im Museum", url="https://example.de/events/k"),
        _event(title="Tanzabend im Festsaal", url="https://example.de/events/t"),
    ]
    titles = [e["title"] for e in score_and_filter_events(events, today=TODAY)]
    assert titles == ["Tanzabend im Festsaal"]


# --------------------------------------------------------------------------
# Timing
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# Favorite sources
# --------------------------------------------------------------------------

def test_a_favorite_source_gets_a_flat_bonus():
    """User: "i really like this website: berlin-buehnen.de ... push events
    from the site in scoring." The bonus applies to the listing source, not
    to venue or category text, and does not fire for other sources."""
    favorite = _event(
        title="InTakt (2026)",
        source_url="https://www.berlin-buehnen.de/de/spielplan",
    )
    other = _event(
        title="InTakt (2026)",
        source_url="https://example.de/events/",
    )
    assert favorite_source_score(favorite) == 16
    assert favorite_source_score(other) == 0
    assert score_event(favorite, TODAY)["score"] == score_event(other, TODAY)["score"] + 16


def test_favorite_source_falls_back_to_url_when_source_url_is_missing():
    ev = _event(url="https://www.berlin-buehnen.de/de/produktion/foo")
    ev.pop("source_url")
    assert favorite_source_score(ev) == 16


def test_weekend_evenings_are_the_sweet_spot():
    fri_evening = _event(date="2026-08-28", time="20:00")   # Friday
    tue_morning = _event(date="2026-09-01", time="10:00")   # Tuesday
    assert timing_score(fri_evening) == 22
    assert timing_score(tue_morning) == -8
    assert timing_score(_event(date="2026-08-29", time="")) == 10  # Saturday, no time
