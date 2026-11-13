#!/usr/bin/env python3
"""The canonical price-status contract for shared event records.

Background
----------
Two pipelines wrote into a field called ``price_status`` with different
vocabularies, and every reader had to know which pipeline produced a row
before it could interpret the value:

* ``ticket_evidence.enrich_evidence()`` (scraping) emitted
  ``free`` / ``known`` / ``range`` / ``unknown``.
* The community pipeline emitted ``confirmed_free`` / ``confirmed_paid`` /
  ``donation_based`` / ``needs_verification`` / ``unknown``.

``unknown`` was the only shared spelling, and it meant the same thing in both,
which is why the collision went unnoticed for a while. Everywhere else a value
had to be attributed to its producer by elimination - a design that works only
until a third producer appears or somebody adds a status.

This module replaces that with one representation that any consumer can read
without knowing where the record came from.

The states
----------
Each state answers one question: *what does the record actually establish about
the price of entry?* "Entry price" is the cheapest way in, so a range's entry
price is its low end.

======================  ==========================================  ===============  =============
status                  meaning                                     entry price      publishable
======================  ==========================================  ===============  =============
``confirmed_free``      free entry, established by evidence        0                yes
``confirmed_paid``      one confirmed price                        that price       if <= cap
``range``               a confirmed low-to-high span               the low end      if low <= cap
``donation_based``      pay-what-you-want; no fixed entry price    not applicable   yes, with note
``needs_verification``  source defers ("on request", "TBA")        unknown          no
``unknown``             no price stated at all                     unknown          no
======================  ==========================================  ===============  =============

How a bare number is read
-------------------------
The three cases are genuinely different, and treating any two of them alike is
what produces either a lost free event or a published unverified price.

**A present positive number is a stated price.** ``12.50`` with no offer object
and no price text is ``confirmed_paid``. This is a deliberate pipeline
decision, inherited from both pipelines this module unifies: a positive figure
reaches a record by one of three routes - a JSON-LD offer, a price regex over
card text, or an official detail page - and each of those has already read a
number the source published. Requiring a second corroboration would downgrade
rows whose price the source did state. ``tests/test_price_status.py`` pins this
so it stays a decision rather than drifting.

**A missing price is ``unknown``** unless independent text establishes
otherwise. Text is the only thing that can settle it: "Eintritt frei" makes it
``confirmed_free``, "auf Spendenbasis" makes it ``donation_based``, and "Preis
auf Anfrage" makes it ``needs_verification``. Silence stays ``unknown``, and no
status can invent a number that is not there.

**A bare zero is not evidence of free entry.** ``confirmed_free`` requires
proof - free admission stated in text, or a structured offer of 0 from the
event's own page. A ``price: 0`` that nothing corroborates is ``unknown``,
because several sources emit zero when they simply failed to find a price.
This is the rule that stops an unverified price being published as "Free", and
it is the one asymmetry in this module that is load-bearing rather than
convenient: a zero is what a *failed* scrape looks like, while a positive
number is what a *successful* one looks like.

Migration
---------
``canonicalize()`` accepts the historical spellings so that records already on
disk - in ``data/events.json``, in a published community issue, in a
qualification artifact - keep working without a rewrite:

========  ==================
legacy    canonical
========  ==================
``free``  ``confirmed_free``
``known`` ``confirmed_paid``
========  ==================

``range`` and ``unknown`` were already spelled canonically and pass through
unchanged, which is why the pre-existing assertions on those two values needed
no edit. ``canonicalize()`` never *downgrades*: a ``confirmed_free`` record is
returned as ``confirmed_free``, so reading and re-writing a current record is
lossless.

Provenance
----------
Canonicalising the status does not discard the evidence behind it. Records keep
``offers``, ``free_admission_confirmed``, ``price_min``/``price_max``,
``evidence`` and ``observed_at``; ``origin_for()`` names which pipeline and
model produced the status, so a reviewer can still tell a community
verification from a Raus detail match. The status says *what is known*; the
provenance says *how it came to be known*.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

SCHEMA_VERSION = "1.0"

CONFIRMED_FREE = "confirmed_free"
CONFIRMED_PAID = "confirmed_paid"
RANGE = "range"
DONATION_BASED = "donation_based"
NEEDS_VERIFICATION = "needs_verification"
UNKNOWN = "unknown"

# Ordered least to most informative, for iteration and documentation.
CANONICAL_STATUSES = (
    UNKNOWN,
    NEEDS_VERIFICATION,
    DONATION_BASED,
    RANGE,
    CONFIRMED_PAID,
    CONFIRMED_FREE,
)

# States that establish a usable entry price.
PRICE_KNOWN_STATUSES = (CONFIRMED_FREE, CONFIRMED_PAID, RANGE)

# Historical spellings, mapped once. Only genuinely equivalent values appear
# here: `free` was always a *proven* free in the evidence model, and `known`
# was always a single confirmed price, so neither mapping loses information.
LEGACY_ALIASES = {
    "free": CONFIRMED_FREE,
    "known": CONFIRMED_PAID,
}

MEANINGS = {
    CONFIRMED_FREE: "Free entry, established by evidence",
    CONFIRMED_PAID: "One confirmed price",
    RANGE: "A confirmed low-to-high span; the entry price is the low end",
    DONATION_BASED: "Pay-what-you-want; no fixed entry price",
    NEEDS_VERIFICATION: "Source defers the price (on request, TBA)",
    UNKNOWN: "No price stated",
}

PUBLISHABLE_WITHOUT_DECIDING = (CONFIRMED_FREE,)


def is_canonical(value: Any) -> bool:
    return str(value or "").strip() in CANONICAL_STATUSES


def canonicalize(value: Any, default: str = UNKNOWN) -> str:
    """Map any historical or current spelling onto a canonical status.

    Unknown input degrades to ``default`` rather than raising: a record with a
    status this module has never heard of is one whose price cannot be
    trusted, and ``unknown`` says exactly that.
    """
    text = str(value or "").strip()
    if not text:
        return default
    if text in CANONICAL_STATUSES:
        return text
    return LEGACY_ALIASES.get(text, default)


def describes_entry_price(status: Any) -> bool:
    """True when the status pins down what entry costs."""
    return canonicalize(status) in PRICE_KNOWN_STATUSES


def entry_price_of(price: Optional[float], status: Any) -> Optional[float]:
    """The entry price the record establishes, or None when it establishes none.

    A ``confirmed_free`` record returns 0.0 even if its stored price is absent,
    because the status *is* the evidence that entry is free. Every other status
    needs a number, and ``range`` uses the low end - which is how both
    pipelines already stored it.
    """
    canonical = canonicalize(status)
    if canonical == CONFIRMED_FREE:
        return 0.0
    if canonical in (CONFIRMED_PAID, RANGE):
        try:
            return float(price) if price is not None else None
        except (TypeError, ValueError):
            return None
    return None


def origin_for(event: Dict[str, Any]) -> Dict[str, str]:
    """Which pipeline and model produced this record's price status.

    Provenance only - nothing decides behaviour from it. It exists so a
    reviewer reading a candidate file can tell a human-facing community
    verification apart from a scraper's structured-offer match.
    """
    if not isinstance(event, dict):
        return {"pipeline": "unknown", "model": "unknown"}
    raw = str(event.get("price_status") or "").strip()
    if raw in LEGACY_ALIASES:
        # A legacy spelling is, by definition, one the evidence model emitted.
        return {
            "pipeline": "scraping",
            "model": "ticket_evidence" if raw == "known" else "raus_publication_gate",
        }
    if event.get("verification") or event.get("community"):
        return {"pipeline": "community", "model": "official_page_verification"}
    if event.get("verification_status") or event.get("offers"):
        return {"pipeline": "scraping", "model": "structured_offer"}
    return {"pipeline": "unknown", "model": "derived"}


def describe(status: Any) -> str:
    """Human sentence for a status, for review summaries and error messages."""
    canonical = canonicalize(status)
    return f"{canonical}: {MEANINGS[canonical]}"
