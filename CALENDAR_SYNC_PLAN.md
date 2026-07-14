# Plan: "Add selected events to my calendar"

## What's built today

The events table (`web/index.html`, deployed as `docs/index.html`) has a
checkbox per row and an **"Add selected to calendar (.ics)"** button. It
generates a standard iCalendar (`.ics`) file client-side from the checked
rows and downloads it - opening/importing that file adds the events to
Google Calendar, Apple Calendar, Outlook, or anything else that reads `.ics`.
This needed no secrets and no backend, so it's live now.

## Why full auto-sync needs more than a static page

GitHub Pages only serves static files - there is no server-side code that
runs per request. Any credential embedded in the page's JavaScript (a Google
Calendar OAuth client secret, a refresh token, a GitHub PAT with `repo`
scope, etc.) would be visible to anyone who opens the browser's dev tools.
**GitHub Actions secrets are only available inside a workflow run** - the
browser has no way to read them, and there's no safe way to hand a "write to
my calendar" credential to arbitrary page visitors. So "click boxes, they
land in my calendar automatically" requires a small piece of trusted
server-side code somewhere, holding the credential, that the static page
calls into.

## Recommended design (not yet built)

1. **Small serverless endpoint** (e.g. a Cloudflare Worker or a Vercel/Netlify
   function - anything that can run a few lines of code and hold a secret).
   It exposes one endpoint, e.g. `POST /add-to-calendar`, that accepts the
   selected events' data (title, date/time, location, description, URL).
2. **Google Calendar API credentials** (OAuth client ID/secret + a
   long-lived refresh token for your Google account) are stored as that
   endpoint's own secret/environment variable - never shipped to the
   browser. Obtaining the refresh token is a one-time manual step: create an
   OAuth client in Google Cloud Console, run through the consent screen once
   (e.g. via Google's OAuth Playground or a short local script), and save the
   resulting refresh token.
3. **The endpoint calls `events.insert`** on the Google Calendar API for each
   submitted event, using the refresh token to mint short-lived access
   tokens as needed.
4. **Where GitHub Actions secrets fit in**: if the endpoint is deployed via a
   GitHub Actions workflow (e.g. `wrangler deploy` for a Cloudflare Worker),
   the Google OAuth credentials would live as encrypted **GitHub Actions
   secrets** in this repo, and the deploy step injects them into the
   endpoint's own secret store at deploy time. They never pass through the
   browser - only through the deploy pipeline, same trust boundary as the
   scraper's `JULES_API_KEY` today.
5. **Frontend change**: the existing "Add selected to calendar" button would
   get a second option ("Sync to Google Calendar directly") that `POST`s the
   selection to that endpoint's URL instead of building a local `.ics` file.

## Why this isn't built yet

It requires standing up and maintaining an external endpoint (outside what
GitHub Pages/Actions alone can host) plus a one-time OAuth setup tied to a
specific calendar account/provider. That's a real piece of infrastructure,
not a code-only change, so it's written up here as a plan rather than
implemented speculatively. If you want to go ahead with it, the main open
decision is *where* to host the endpoint (Cloudflare Workers has a
generous free tier and is the lowest-effort option) and confirming Google
Calendar (vs. Outlook/Apple) is the right target.
