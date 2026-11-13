/* Community picks frontend.
 *
 * Reads latest.json — the promoted, human-approved issue — and renders it.
 * It never fetches a candidate file: an unapproved event must not be reachable
 * from the page at all, so the "empty state" case is a real, expected state
 * rather than a bug. No event data is hardcoded here.
 *
 * Everything is built with createElement/textContent rather than innerHTML:
 * titles, descriptions and reasons all come from scraped pages, and a venue
 * whose blurb contains markup should render as text, not execute.
 */
(function () {
  "use strict";

  var DATA_URL = "latest.json";
  var FREE_STATUSES = { confirmed_free: true, donation_based: true };

  var state = { issue: null, events: [] };

  // ---------------------------------------------------------------- utils

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  var DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  var MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
                     "July", "August", "September", "October", "November", "December"];

  function parseIsoDate(value) {
    var m = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(String(value || "").trim());
    if (!m) return null;
    return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  }

  function fmtDay(value) {
    var d = parseIsoDate(value);
    if (!d) return "Date to be confirmed";
    return DAY_NAMES[d.getDay()] + ", " + d.getDate() + " " + MONTH_NAMES[d.getMonth()];
  }

  function fmtShortDay(value) {
    var d = parseIsoDate(value);
    if (!d) return "";
    return DAY_NAMES[d.getDay()].slice(0, 3) + " " + d.getDate() + "." + (d.getMonth() + 1) + ".";
  }

  function fmtRange(start, end) {
    var a = parseIsoDate(start), b = parseIsoDate(end);
    if (!a || !b) return "";
    var sameMonth = a.getMonth() === b.getMonth() && a.getFullYear() === b.getFullYear();
    var left = a.getDate() + ". " + (sameMonth ? "" : MONTH_NAMES[a.getMonth()] + " ");
    return left + "- " + b.getDate() + ". " + MONTH_NAMES[b.getMonth()] + " " + b.getFullYear();
  }

  function fmtTimestamp(value) {
    if (!value) return "";
    var d = new Date(value);
    if (isNaN(d.getTime())) return String(value);
    return d.toLocaleString("en-GB", {
      day: "numeric", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit", timeZone: "Europe/Berlin"
    }) + " (Berlin)";
  }

  function priceClass(event) {
    if (event.price_status === "confirmed_free") return "is-free";
    if (event.price_status === "donation_based") return "is-donation";
    return "";
  }

  function priceBadgeClass(event) {
    if (event.price_status === "confirmed_free") return "badge badge-free";
    if (event.price_status === "donation_based") return "badge badge-donation";
    return "badge badge-paid";
  }

  function isFree(event) {
    return FREE_STATUSES[event.price_status] === true && !event.price_eur;
  }

  function safeUrl(value) {
    // Only http(s) links are rendered; anything else (javascript:, data:) is
    // dropped rather than trusted, since the URL came from a scraped page.
    if (!value) return "";
    try {
      var parsed = new URL(String(value), window.location.href);
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return "";
      return parsed.href;
    } catch (e) {
      return "";
    }
  }

  function hostOf(value) {
    var url = safeUrl(value);
    if (!url) return "";
    try { return new URL(url).hostname.replace(/^www\./, ""); } catch (e) { return ""; }
  }

  function placeholderMark(title) {
    var words = String(title || "").trim().split(/\s+/).filter(Boolean);
    if (!words.length) return "•";
    return words.slice(0, 2).map(function (w) { return w.charAt(0); }).join("");
  }

  // -------------------------------------------------------------- card UI

  function buildMedia(event) {
    var media = el("div", "card-media");
    var src = safeUrl(event.image_url);

    if (src) {
      var img = document.createElement("img");
      img.src = src;
      img.alt = "";
      img.loading = "lazy";
      img.decoding = "async";
      img.referrerPolicy = "no-referrer";
      // A dead image is common (organisers rotate artwork), so fall back to
      // the same placeholder a card with no image uses rather than showing a
      // broken-image glyph.
      img.addEventListener("error", function () {
        media.classList.add("is-placeholder");
        img.remove();
        media.appendChild(el("span", "placeholder-mark", placeholderMark(event.title)));
      });
      media.appendChild(img);
    } else {
      media.classList.add("is-placeholder");
      media.appendChild(el("span", "placeholder-mark", placeholderMark(event.title)));
    }

    var badges = el("div", "badge-row");
    badges.appendChild(el("span", priceBadgeClass(event), event.price_label || "Price"));
    media.appendChild(badges);
    return media;
  }

  function buildCard(event) {
    var card = el("article", "card");

    card.appendChild(buildMedia(event));

    var body = el("div", "card-body");

    var when = fmtShortDay(event.date) + (event.time ? " · " + event.time : "");
    body.appendChild(el("p", "card-when", when));

    var title = el("h3", "card-title");
    var link = safeUrl(event.event_url);
    if (link) {
      var anchor = document.createElement("a");
      anchor.href = link;
      anchor.target = "_blank";
      anchor.rel = "noopener noreferrer";
      anchor.textContent = event.title || "Untitled event";
      title.appendChild(anchor);
    } else {
      title.textContent = event.title || "Untitled event";
    }
    body.appendChild(title);

    var where = el("p", "card-where");
    if (event.venue) where.appendChild(document.createTextNode(event.venue));
    if (event.district) {
      if (event.venue) where.appendChild(document.createTextNode(" · "));
      where.appendChild(el("span", "district", event.district));
    }
    if (!event.venue && !event.district) where.textContent = "Location to be confirmed";
    body.appendChild(where);

    if (event.recommendation_reason) {
      body.appendChild(el("p", "card-reason", event.recommendation_reason));
    }

    var foot = el("div", "card-foot");
    foot.appendChild(el("span", "card-price " + priceClass(event), event.price_label || ""));
    if (link) {
      var out = document.createElement("a");
      out.className = "card-link";
      out.href = link;
      out.target = "_blank";
      out.rel = "noopener noreferrer";
      out.textContent = "Official page →";
      foot.appendChild(out);
    }
    body.appendChild(foot);

    var host = hostOf(event.official_source_url || event.event_url);
    if (host) body.appendChild(el("span", "verified-note", "Checked on " + host));

    card.appendChild(body);
    return card;
  }

  function fillGrid(id, events) {
    var grid = document.getElementById(id);
    grid.replaceChildren();
    events.forEach(function (event) { grid.appendChild(buildCard(event)); });
    toggleSection(id, events.length > 0);
  }

  // A section with nothing in it is hidden entirely rather than shown empty,
  // and its nav chip goes with it so the nav never offers a dead anchor.
  function toggleSection(id, show) {
    var node = document.getElementById(id);
    if (!node) return;
    node.hidden = !show;
    var navLink = document.querySelector('.hero-nav a[href="#' + id + '"]');
    if (navLink) navLink.hidden = !show;
  }

  // ------------------------------------------------------------ sections

  function renderCategories(events) {
    var host = document.getElementById("category-groups");
    host.replaceChildren();

    var groups = {};
    events.forEach(function (event) {
      var label = event.category_label || "Other distinctive experiences";
      (groups[label] = groups[label] || []).push(event);
    });

    var labels = Object.keys(groups).sort(function (a, b) {
      if (groups[b].length !== groups[a].length) return groups[b].length - groups[a].length;
      return a.localeCompare(b);
    });

    labels.forEach(function (label) {
      var block = el("div", "category-block");
      var head = el("div", "section-head");
      head.appendChild(el("h3", null, label));
      var note = el("p", "section-note");
      note.textContent = groups[label].length === 1 ? "1 event" : groups[label].length + " events";
      head.appendChild(note);
      block.appendChild(head);
      var grid = el("div", "card-grid");
      groups[label].forEach(function (event) { grid.appendChild(buildCard(event)); });
      block.appendChild(grid);
      host.appendChild(block);
    });

    toggleSection("categories", events.length > 0);
  }

  function renderIssue(issue) {
    var events = (issue.events || []).filter(function (event) {
      return event && event.title && event.date;
    });
    state.issue = issue;
    state.events = events;

    var week = issue.issue_week || {};
    document.getElementById("week-range").textContent =
      week.start ? fmtRange(week.start, week.end) : "";
    document.getElementById("week-heading").textContent = "This week in Berlin";
    var freeCount = events.filter(isFree).length;
    document.getElementById("week-sub").textContent =
      events.length + (events.length === 1 ? " event" : " events") +
      ", each confirmed on the organiser's own page" +
      (freeCount ? " \u2014 " + freeCount + " of them free to attend." : ".");

    var free = events.filter(isFree);
    fillGrid("free-grid", free);
    fillGrid("selection-grid", events);
    fillGrid("affordable-grid", events.filter(function (e) { return !isFree(e); }));
    renderCategories(events);

    document.getElementById("freshness").textContent =
      "Published " + (fmtTimestamp(issue.published_at) || "recently") +
      " · week of " + (week.start || "?") + " to " + (week.end || "?") +
      " · " + events.length + " approved events.";

    document.getElementById("empty").hidden = events.length > 0;
    if (!events.length) {
      document.getElementById("week-sub").textContent =
        "No events were approved for publication this week.";
    }
    document.getElementById("status").replaceChildren();
  }

  var EMPTY_COPY = "This page only ever shows events a human editor has approved " +
    "for publication. Candidates are not displayed here, so an empty week means " +
    "the weekly review has not been published yet \u2014 not that Berlin has nothing on.";

  function showEmpty(heading, copy) {
    document.getElementById("status").replaceChildren();
    document.getElementById("empty").hidden = false;
    document.getElementById("empty-heading").textContent =
      heading || "No approved issue for this week yet";
    document.getElementById("empty-copy").textContent = copy || EMPTY_COPY;
  }

  function showError(message) {
    var status = document.getElementById("status");
    status.replaceChildren();
    status.appendChild(el("p", "status-error", message));
  }

  // ----------------------------------------------------------------- boot

  function load() {
    fetch(DATA_URL, { cache: "no-cache" })
      .then(function (response) {
        if (response.status === 404) {
          showEmpty("No approved issue for this week yet");
          return null;
        }
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(function (issue) {
        if (!issue) return;
        if (!issue.events || !issue.events.length) {
          showEmpty("This week's issue contains no events",
            "The published issue was reviewed and approved, but no event met the " +
            "publication rules for this week. Nothing was padded to fill it.");
          return;
        }
        renderIssue(issue);
      })
      .catch(function (error) {
        showError("Could not load this week's picks (" + error.message + ").");
        showEmpty("The published data could not be read",
          "The page reached latest.json but could not parse it. This is a bug in the " +
          "published file, not an empty week.");
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", load);
  } else {
    load();
  }
})();
