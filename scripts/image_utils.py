#!/usr/bin/env python3
"""Optional event-image discovery and validation.

The scraped event records never carried an image, which is why the community
page had nothing to show above the fold. This module adds one, without ever
letting the attempt change whether an event is valid: every entry point here
returns a plain string (or None) and swallows its own parse errors, and
``validate_event()`` treats the field as decoration rather than data.

Sources are tried strongest first, because each is a different strength of
claim:

  1. ``application/ld+json`` Event nodes - the publisher is literally telling
     machines what the event's image is.
  2. Open Graph (``og:image``, ``og:image:url``, ``og:image:secure_url``) on
     the event's own page - the page's nominated preview image.
  3. Twitter card (``twitter:image``, ``twitter:image:src``, and the
     ``name=`` variants some sites emit instead of ``property=``).
  4. The event card's own ``<img>``/``<picture>`` markup, including the
     lazy-loading attributes (``data-src``, ``data-original``, ``srcset``)
     that sites use instead of ``src``.

The fourth is the weakest signal and the one that needs guarding: a card's
markup also carries the site logo, category glyphs, author avatars, a pixel
for the ad tracker and the background texture. ``looks_decorative()`` is the
filter for exactly that, and it is deliberately allowed to miss an image
rather than to publish a logo as an event poster.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urljoin, urlparse

# Names/labels that mark an image as page furniture rather than artwork.
DECORATIVE_HINTS = (
    "logo", "avatar", "icon", "sprite", "spacer", "pixel", "tracking", "beacon",
    "badge", "favicon", "gravatar", "placeholder", "blank", "1x1", "transparent",
    "nav-", "-nav", "header-", "footer-", "arrow", "chevron", "burger", "search",
    "social", "share", "payment", "sponsor", "advert", "banner-ad",
)

# File-name fragments of known tracker/placeholder paths.
DECORATIVE_URL_FRAGMENTS = (
    "google-analytics", "googletagmanager", "facebook.com/tr", "doubleclick",
    "/pixel.gif", "/pixel.png", "spacer.gif", "1x1.",
)

IMAGE_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif", ".bmp", ".tif", ".tiff",
)


def _as_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _first_url_from_candidates(candidates: Iterable[Any]) -> str:
    """First usable URL from a mixed list of strings, dicts and nested lists.

    schema.org's ``image`` property is genuinely polymorphic: a URL string, an
    array of URL strings, an ``ImageObject``, an array of ``ImageObject``, or
    an ``ImageObject`` whose ``url`` is itself a list. Flattening first keeps
    the call sites from each re-implementing half of that.
    """
    for candidate in candidates:
        if isinstance(candidate, str):
            if candidate.strip():
                return candidate.strip()
        elif isinstance(candidate, list):
            found = _first_url_from_candidates(candidate)
            if found:
                return found
        elif isinstance(candidate, dict):
            found = _url_from_image_object(candidate)
            if found:
                return found
    return ""


def _url_from_image_object(node: Dict[str, Any]) -> str:
    for key in ("url", "contentUrl", "thumbnailUrl", "src", "@id"):
        value = node.get(key)
        found = _first_url_from_candidates(value if isinstance(value, list) else [value])
        if found:
            return found
    return ""


def jsonld_image(node: Dict[str, Any]) -> str:
    """The image URL an Event JSON-LD node declares, or ""."""
    if not isinstance(node, dict):
        return ""
    for key in ("image", "thumbnailUrl", "primaryImageOfPage"):
        value = node.get(key)
        if value is None:
            continue
        found = _first_url_from_candidates(value if isinstance(value, list) else [value])
        if found:
            return found
    return ""


META_IMAGE_KEYS = (
    # Open Graph, in the order a page should be read.
    ("og:image:secure_url", "og_image"),
    ("og:image:url", "og_image"),
    ("og:image", "og_image"),
    # Twitter card.
    ("twitter:image:src", "twitter_image"),
    ("twitter:image", "twitter_image"),
)


def meta_images(html: str) -> List[Dict[str, str]]:
    """Every preview image a page nominates through meta tags.

    Both ``property=`` and ``name=`` spellings are read: Open Graph specifies
    ``property``, but a fair number of German venue sites emit ``name`` and
    would otherwise look like they had no preview image at all.

    Ordered by *strength of claim*, not document order: Open Graph is the page
    explicitly nominating its preview image, a Twitter card only describes one
    platform's thumbnail. A page that lists its Twitter tags first - which
    several do, because their SEO plugin writes them above the OG block -
    should still be read OG-first.
    """
    if not html:
        return []
    # Ranked rather than appended in document order, so both the
    # "og:image:secure_url beats og:image" rule and the "Open Graph beats
    # Twitter" rule fall out of one ordering.
    rank = {known: index for index, (known, _source) in enumerate(META_IMAGE_KEYS)}
    buckets: Dict[str, List[Dict[str, object]]] = {"og_image": [], "twitter_image": []}
    seen = set()
    # A light regex rather than a full parse: this runs once per page, must
    # never throw on malformed markup, and only needs attribute pairs.
    for match in re.finditer(r'<meta\b[^>]*>', html, re.IGNORECASE):
        tag = match.group(0)
        key_match = re.search(
            r'(?:property|name|itemprop)\s*=\s*["\']([^"\']+)["\']', tag, re.IGNORECASE
        )
        content_match = re.search(
            r'content\s*=\s*["\']([^"\']*)["\']', tag, re.IGNORECASE
        )
        if not key_match or not content_match:
            continue
        key = key_match.group(1).strip().lower()
        value = content_match.group(1).strip()
        if not value or key in seen:
            continue
        for known, source in META_IMAGE_KEYS:
            if key == known:
                seen.add(key)
                buckets[source].append({"url": value, "source": source, "rank": rank[known]})
                break
    ordered = buckets["og_image"] + buckets["twitter_image"]
    ordered.sort(key=lambda entry: entry["rank"])
    return [{"url": entry["url"], "source": entry["source"]} for entry in ordered]


SRCSET_SPLIT_RE = re.compile(r'\s*,\s*')


def _best_from_srcset(srcset: str) -> str:
    """The largest candidate in a ``srcset``, or "".

    Widths and pixel densities are both scored on one axis (width first, then
    density) because a card that offers ``640w, 1280w`` wants the 1280 and one
    that offers ``1x, 2x`` wants the 2x.
    """
    best_url, best_score = "", -1.0
    for entry in SRCSET_SPLIT_RE.split(srcset or ""):
        parts = entry.strip().split()
        if not parts:
            continue
        url = parts[0]
        score = 0.0
        if len(parts) > 1:
            descriptor = parts[1].lower()
            try:
                if descriptor.endswith("w"):
                    score = float(descriptor[:-1])
                elif descriptor.endswith("x"):
                    score = float(descriptor[:-1]) * 1000
            except ValueError:
                score = 0.0
        if score > best_score and url:
            best_url, best_score = url, score
    return best_url


LAZY_IMAGE_ATTRS = (
    "data-src", "data-original", "data-lazy-src", "data-srcset", "data-original-src",
    "data-image", "data-bg", "srcset", "src",
)


def looks_decorative(
    url: str = "", alt: str = "", classes: str = "", width: Any = None, height: Any = None
) -> bool:
    """True when an image is page furniture rather than event artwork.

    Errs towards rejecting: a card with no usable poster renders a graceful
    placeholder, whereas a card showing the site's logo as the event image is
    actively wrong.
    """
    haystack = " ".join(str(part or "") for part in (url, alt, classes)).lower()
    if not haystack.strip():
        return True
    if any(fragment in haystack for fragment in DECORATIVE_URL_FRAGMENTS):
        return True
    for hint in DECORATIVE_HINTS:
        if hint in haystack:
            return True
    try:
        if width is not None and int(str(width).strip()) <= 48:
            return True
        if height is not None and int(str(height).strip()) <= 48:
            return True
    except (TypeError, ValueError):
        pass
    # A 1x1 spacer is invisible even when nothing else marks it as one.
    dims = re.search(r'[/_-](\d{1,2})x(\d{1,2})\.(?:gif|png)', url or "", re.IGNORECASE)
    if dims and int(dims.group(1)) <= 2 and int(dims.group(2)) <= 2:
        return True
    return False


def resolve_image_url(url: str, page_url: str) -> str:
    """Absolute http(s) image URL, or "" for anything unusable."""
    raw = _as_str(url).replace("\\/", "/")
    if not raw:
        return ""
    if raw.startswith(("data:", "javascript:", "mailto:", "#")):
        return ""
    try:
        absolute = urljoin(page_url or "", raw)
        parsed = urlparse(absolute)
    except ValueError:
        return ""
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    return absolute


def _image_from_element(element) -> str:
    """Best image URL inside one card element, or ""."""
    if element is None:
        return ""
    best, best_score = "", -1
    for img in element.find_all("img"):
        for attr in LAZY_IMAGE_ATTRS:
            value = img.get(attr)
            if not value:
                continue
            if attr.endswith("srcset"):
                candidate = _best_from_srcset(value)
            else:
                candidate = value
            if not candidate:
                continue
            if looks_decorative(
                candidate,
                img.get("alt", ""),
                " ".join(img.get("class", []) or []),
                img.get("width"),
                img.get("height"),
            ):
                continue
            score = 3 if attr.startswith("data-") else 2 if attr == "srcset" else 1
            if score > best_score:
                best, best_score = candidate, score
            break
    if best:
        return best
    for picture in element.find_all("picture"):
        for source in picture.find_all("source"):
            candidate = _best_from_srcset(source.get("srcset") or source.get("data-srcset") or "")
            if candidate and not looks_decorative(candidate, source.get("media", "")):
                return candidate
    return ""


def card_image(element, page_url: str) -> str:
    """Resolved image URL from a card, including nested picture/source markup."""
    found = _image_from_element(element)
    return resolve_image_url(found, page_url) if found else ""


def attach_image(
    event: Dict[str, Any],
    url: str,
    source: str,
    page_url: str,
    *,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """Set image fields on ``event`` when it has none, or when told to.

    Never raises: image extraction is decoration, so a bad value on one row
    must not stop a page's other events from being published.
    """
    try:
        if not isinstance(event, dict):
            return event
        if event.get("image_url") and not overwrite:
            return event
        resolved = resolve_image_url(url, page_url)
        if not resolved:
            return event
        event["image_url"] = resolved
        event["image_source"] = source
        event.setdefault("image_verified", None)
        event.setdefault("image_checked_at", None)
    except Exception:  # noqa: BLE001 - decoration must never fail a scrape
        pass
    return event


def best_document_image(html: str, page_url: str) -> Optional[Dict[str, str]]:
    """Highest-priority image the document itself declares, or None."""
    for entry in meta_images(html):
        if looks_decorative(entry["url"]):
            continue
        resolved = resolve_image_url(entry["url"], page_url)
        if resolved:
            return {"url": resolved, "source": entry["source"]}
    return None


# --------------------------------------------------------------------------
# Bounded HTTP validation
# --------------------------------------------------------------------------

# An event poster is a normal web asset; anything an order of magnitude past
# this is either a mis-served video or a hotlink protection page.
MAX_IMAGE_BYTES = 8 * 1024 * 1024
IMAGE_CHECK_TIMEOUT = (3.05, 8.0)


def check_image_url(url: str, timeout=IMAGE_CHECK_TIMEOUT, max_bytes: int = MAX_IMAGE_BYTES,
                    session=None) -> Dict[str, Any]:
    """Bounded check that a URL really serves an image.

    Returns ``{ok, reason, content_type, bytes}``. A failed check is not an
    error - it means "do not trust this image", which the frontend renders as
    its own placeholder rather than a broken tile.
    """
    result = {"ok": False, "reason": "", "content_type": "", "bytes": None}
    if not url or not url.startswith(("http://", "https://")):
        result["reason"] = "not_http"
        return result
    try:
        import requests  # imported lazily so parsing stays importable
    except Exception:  # noqa: BLE001
        result["reason"] = "no_http_client"
        return result

    getter = session.get if session is not None else requests.get
    try:
        response = getter(url, timeout=timeout, stream=True, allow_redirects=True,
                          headers={"Accept": "image/avif,image/webp,image/*,*/*;q=0.8"})
        with response:
            content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            result["content_type"] = content_type
            length_header = response.headers.get("Content-Length")
            if length_header:
                try:
                    if int(length_header) > max_bytes:
                        result["reason"] = "too_large"
                        return result
                except ValueError:
                    pass
            if response.status_code >= 400:
                result["reason"] = f"http_{response.status_code}"
                return result
            if not content_type.startswith("image/"):
                result["reason"] = "not_an_image"
                return result
            read = 0
            for chunk in response.iter_content(8192):
                read += len(chunk)
                if read > max_bytes:
                    result["reason"] = "too_large"
                    return result
                if read >= 2048:
                    break
            result["bytes"] = read
            if read == 0:
                result["reason"] = "empty"
                return result
        result["ok"] = True
        return result
    except Exception as exc:  # noqa: BLE001 - any transport failure is "unverified"
        result["reason"] = type(exc).__name__
        return result


def verify_event_images(
    events: List[Dict[str, Any]],
    max_checks: int = 20,
    check=check_image_url,
) -> List[Dict[str, Any]]:
    """Bounded image validation over a batch of events.

    Only events that already carry an image are checked, and only up to
    ``max_checks`` of them: the weekly run must stay a fixed tail cost, not a
    second crawl of the whole calendar.
    """
    from datetime import datetime, timezone

    checked = 0
    for event in events or []:
        if checked >= max_checks:
            break
        url = event.get("image_url") or ""
        if not url or event.get("image_verified") is not None:
            continue
        checked += 1
        outcome = check(url)
        event["image_verified"] = bool(outcome.get("ok"))
        event["image_checked_at"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        if not outcome.get("ok"):
            event["image_check_reason"] = outcome.get("reason", "")
    return events
