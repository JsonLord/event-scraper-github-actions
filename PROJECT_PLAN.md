# Project Plan: Self-Healing Event Scraper Hub

## 1. Project Description
**Vision and Goals**
The Self-Healing Event Scraper Hub is a zero-maintenance event aggregation platform. It leverages Jules AI to autonomously repair broken scrapers in a CI/CD environment, ensuring that affordable Berlin events (≤15€) are always up-to-date.

**In-app Integrations**
- **GitHub Actions**: Orchestrates the autonomous repair cycle.
- **CloakBrowser**: Provides stealth navigation for anti-bot bypass.
- **Jules AI**: Analyzes HTML failures and generates code fixes.
- **FastAPI**: Serves the event data and manages webhook registrations.

**FastAPI Setup**
- **App Structure**: Modular design with `api/`, `models/`, and `services/`.
- **Routers**: Clean separation of event listing, status monitoring, and webhook management.
- **Config**: Pydantic-settings for environment-driven configuration.

## 2. Tasks and Tests

### Backend Development
- **Task**: Implement FastAPI core with `/events` and `/status` endpoints.
  - **Test**: `GET /health` returns `{"status": "ok"}`.
- **Task**: Standardize scraper outputs to unified JSON schema.
  - **Test**: Run `scripts/rausgegangen_scraper.py` and verify `events.json` contains `title`, `price`, and `url`.

### Autonomous Logic
- **Task**: Implement `scripts/autonomous_repair.py` loop.
  - **Test**: `pytest tests/test_repair_logic.py` verifies that a failed scrape triggers Jules AI.

### Infrastructure
- **Task**: Configure GitHub Actions with matrix strategy for parallel scraping.
  - **Test**: Verify `.github/workflows/weekly-jules-review.yml` is correctly formatted.

## 3. Functionality Expectations
- **User Perspective**:
  - Access a JSON API of affordable events.
  - Receive real-time notifications via webhooks.
  - View scraper health status via a dashboard endpoint.
- **Technical Perspective**:
  - **Self-Healing**: System automatically creates PRs or updates its own code when websites change.
  - **Stealth**: High-score bot bypass using CloakBrowser.
- **Constraints**:
  - Limited to Berlin events.
  - Hard limit of 15€ for event inclusion.

## 4. API Endpoints

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/health` | GET | Health check. |
| `/events` | GET | List all events (reads from `docs/events.json`). |
| `/status` | GET | Get scraping health and last run statistics. |
| `/webhooks` | POST | Register a new notification URL. |
