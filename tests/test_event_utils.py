"""Regression tests for the shared normalisation and validation layer.

Every case here is taken from a row that the published GitHub Pages run
actually shipped, so a regression reproduces a user-visible defect rather than
an abstract edge case.
"""

from datetime import date

from scripts.event_utils import (
    clean_text,
    clean_url,
    collapse_repeated_phrases,
    dedupe_events,
    extract_venue,
    format_price_label,
    has_berlin_signal,
    looks_synthetic_title,
    normalize_date,
    parse_date,
    parse_price,
    parse_time,
    validate_event,
)

TODAY = date(2026, 8, 27)
WINDOW_END = date(2026, 9, 3)


# --------------------------------------------------------------------------
# Time
# --------------------------------------------------------------------------

def test_dotted_date_is_not_read_as_a_time():
    """All 22 berlin-buehnen rows published a "time" of "27:08"."""
    assert parse_time("DO 27.08.2026 16:30 Open Air") == "16:30"
    assert parse_time("27.08.2026") == ""


def test_meridiem_times_are_normalised_to_24_hour():
    assert parse_time("5:00 PM") == "17:00"
    assert parse_time("12:00 AM") == "00:00"
    assert parse_time("12:30 PM") == "12:30"
    assert parse_time("ab 18 Uhr") == "18:00"


# --------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------

def test_jsonld_dates_are_zero_padded():
    """"2026-8-29" broke both the frontend date sort and the .ics export."""
    assert normalize_date("2026-8-29") == "2026-08-29"
    assert normalize_date("2026-08-29T21:00+02:00") == "2026-08-29"


def test_unparseable_date_returns_none_rather_than_today():
    assert parse_date("no date in this text") is None


def test_yearless_date_resolves_to_the_nearest_occurrence():
    """Lake Studios' archive rows were all pushed out to 2027."""
    assert parse_date("Fr 30 Jun UNFINISHED FRIDAYS #100", TODAY) == "2026-06-30"


def test_card_date_is_preferred_over_listing_page_date():
    assert parse_date("So, 30. Aug | 12:00 FluxFM Sommerlounge", TODAY) == "2026-08-30"


# --------------------------------------------------------------------------
# Price
# --------------------------------------------------------------------------

def test_price_label_keeps_cents():
    """€12.10 rendered as "€12.1" and €9.50 as "€9.5"."""
    assert format_price_label(12.10) == "€12.10"
    assert format_price_label(9.5) == "€9.50"
    assert format_price_label(15.0) == "€15"
    assert format_price_label(0.0) == "Free"
    assert format_price_label(None) == "Check site"


def test_unstated_price_is_none_not_free():
    assert parse_price("Line-up: gãl, GVMEDNA, ELLA WAX") is None
    assert parse_price("Free admission") == 0.0
    assert parse_price("5,00 €") == 5.0


# --------------------------------------------------------------------------
# Text
# --------------------------------------------------------------------------

def test_html_and_entities_are_stripped_from_descriptions():
    raw = "<p>Synthwave and Cyberpunk.<br /> Vector Seven &#8211; Cyberpunk &#038; more</p>"
    assert clean_text(raw) == "Synthwave and Cyberpunk. Vector Seven – Cyberpunk & more"


def test_repeated_listing_labels_are_collapsed():
    noisy = "Open Air Open Air Theater Theater Musiktheater Musiktheater"
    assert clean_text(noisy) == "Open Air Theater Musiktheater"


def test_short_genuine_repetition_is_preserved():
    assert collapse_repeated_phrases("Bye Bye Berlin") == "Bye Bye Berlin"


def test_club_name_keeps_its_leading_punctuation():
    assert clean_text("://about blank") == "://about blank"


# --------------------------------------------------------------------------
# Titles and venues
# --------------------------------------------------------------------------

def test_placeholder_and_header_titles_are_rejected():
    assert looks_synthetic_title("Event 12")
    assert looks_synthetic_title("URL Source: https://www.eventbrite.com/d/x")
    assert looks_synthetic_title("Zum Spielplan")
    assert not looks_synthetic_title("XTRUDE x LASTER w/ Alarico")


def test_venue_is_recovered_from_listing_text():
    assert extract_venue(
        "So, 30. Aug | 12:00 FluxFM Sommerlounge FluxBau Free admission",
        "Fluxfm Sommerlounge",
    ) == "FluxBau"
    assert extract_venue(
        "29 Aug Eröffnungs-Wochenende Deutsche Oper Berlin Sa, 29. Aug 2026, 12:00",
        "Eröffnungs-Wochenende",
    ) == "Deutsche Oper Berlin"


def test_unterminated_run_is_not_guessed_as_a_venue():
    assert extract_venue("DO 27.08.2026 16:30 | Luftschloss Tempelhofer Feld Emil und die Detektive") == ""


def test_date_venue_pseudo_title_is_split_into_name_and_venue():
    """berlin-buehnen published "27.08.2026, 16:30| Luftschloss..." as a name."""
    event = validate_event(
        {
            "title": "27.08.2026, 16:30| Luftschloss Tempelhofer Feld",
            "date": "2026-08-27",
            "time": "27:08",
            "price": None,
            "description": (
                "DO 27.08.2026 16:30 Open Air Open Air Theater Theater Emil und die "
                "Detektive Luftschloss Tempelhofer Feld Emil und die Detektive Nach dem "
                "Kinderbuch-Klassiker von Erich Kästner."
            ),
            "url": "https://www.berlin-buehnen.de/de/spielplan",
            "venue": "",
        },
        "https://www.berlin-buehnen.de/de/spielplan",
        TODAY,
        WINDOW_END,
    )
    assert event["title"] == "Emil und die Detektive"
    assert event["venue"] == "Luftschloss Tempelhofer Feld"
    assert event["time"] == "16:30"
    assert event["has_detail_link"] is False


# --------------------------------------------------------------------------
# Berlin scoping and validation
# --------------------------------------------------------------------------

def test_source_url_alone_is_not_a_berlin_signal():
    """The Meetup listing URL contains "Berlin" as its own query string."""
    assert not has_berlin_signal({
        "title": "Garden Piano Walk At Golden Gate Park",
        "url": "https://www.meetup.com/gist-irl/events/315702861/",
        "source_url": "https://www.meetup.com/find/?userFreeform=Berlin%2C+Germany",
    })


def test_san_francisco_meetup_is_rejected_for_a_berlin_query():
    assert validate_event(
        {
            "title": "20s & 30s Late Night Comedy & Pizza in North Beach!",
            "date": "2026-08-27",
            "time": "6:30 PM",
            "price": 0,
            "url": "https://www.meetup.com/gist-irl/events/315690769/",
            "venue": "Online",
        },
        "https://www.meetup.com/find/?userFreeform=Berlin%2C+Germany",
        TODAY,
        WINDOW_END,
        require_berlin_signal=True,
    ) is None


def test_berlin_event_from_a_global_platform_is_kept():
    event = validate_event(
        {
            "title": "Berlin Tech Founders Mixer",
            "date": "2026-08-28",
            "time": "7:00 PM",
            "price": None,
            "url": "https://www.meetup.com/berlin-startups/events/12345/",
            "venue": "",
        },
        "https://www.meetup.com/find/?location=de--Berlin",
        TODAY,
        WINDOW_END,
        require_berlin_signal=True,
    )
    assert event["title"] == "Berlin Tech Founders Mixer"
    assert event["time"] == "19:00"


def test_berlin_specific_source_keeps_a_foreign_sounding_name():
    """"Amsterdam Techno Records" is a real night at ://about blank."""
    event = validate_event(
        {
            "title": "Amsterdam Techno Records",
            "date": "2026-8-27",
            "time": "20:00",
            "price": None,
            "description": "<p>LINE UP</p><p>gãl &#8211; TAKT130</p>",
            "url": "https://www.theclubmap.com/events/amsterdam-techno-records/",
            "venue": "://about blank",
        },
        "https://www.theclubmap.com/berlin-techno-partys/",
        TODAY,
        WINDOW_END,
    )
    assert event["date"] == "2026-08-27"
    assert event["venue"] == "://about blank"
    assert event["price"] is None


def test_events_outside_the_window_are_dropped():
    for out_of_range in ("2027-07-24", "2019-09-05", "2026-11-20"):
        assert validate_event(
            {"title": "UNFINISHED FRIDAYS #93", "date": out_of_range, "price": None,
             "url": "https://lakestudiosberlin.com/event/uf-93/"},
            "https://lakestudiosberlin.com/unfinished-fridays/",
            TODAY,
            WINDOW_END,
        ) is None


def test_placeholder_row_is_rejected_entirely():
    assert validate_event(
        {"title": "Event 11", "date": "2026-08-27", "price": 0, "venue": "Online",
         "url": "https://www.meetup.com/find/?x=1"},
        "https://www.meetup.com/find/?x=1",
        TODAY,
        WINDOW_END,
    ) is None


def test_tracking_parameters_are_stripped():
    assert clean_url(
        "https://www.meetup.com/gist-irl/events/315702861/"
        "?recId=32a4&recSource=ml-popular&searchId=6f52&eventOrigin=find_page"
    ) == "https://www.meetup.com/gist-irl/events/315702861/"


def test_dedupe_matches_across_differing_date_formats():
    events = [
        {"title": "Giselle", "date": "2026-08-29", "url": "https://a.de/giselle", "has_detail_link": True},
        {"title": "Giselle", "date": "2026-08-29", "url": "https://a.de/giselle", "has_detail_link": True},
    ]
    assert len(dedupe_events(events)) == 1
