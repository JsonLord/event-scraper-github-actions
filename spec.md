# Event Scraper System Specification

## Objective
Create a GitHub repository for the event scraper system, investigate Jules API endpoints used by `/home/leon/development/desk_agent_2.0` project, replicate those endpoints in the new repo, integrate CloakBrowser (https://github.com/CloakHQ/cloakbrowser) for site navigation, and set up the system to use user-provided .env file for Jules API authentication.

## Important Details
- User has desk_agent_2.0 project at `/home/leon/development/desk_agent_2.0` that uses Jules API endpoints
- Jules API endpoint base: `https://jules.googleapis.com/v1alpha`
- Authentication uses `X-Goog-Api-Key` header
- System needs to: scrape events, validate via CloakBrowser navigation, update results on sites, and run improvement cycles
- CloakBrowser will be included as part of the repo scripts for site navigation
- User will provide .env file with Jules API credentials for use in GitHub repo

## Jules API Endpoints Identified (Complete Inventory)

### Core Endpoints (from agent.py, server.js, loopEngine.js, wrapperService.js)

1. **GET /sources**
   - Purpose: List all available sources (GitHub repos connected to Jules)
   - Used in: `hermesToolListSources()`, `list_sources()` in agent.py
   - Response: `{ sources: [...] }`

2. **POST /sessions**
   - Purpose: Create a new Jules session
   - Used in: `hermesToolStartJulesSession()`, `create_session()` in agent.py, `handleSessionRequest()` in wrapperService.js
   - Request body:
     ```json
     {
       "title": "Session title",
       "prompt": "Task prompt",
       "automationMode": "AUTO_CREATE_PR",
       "sourceContext": {
         "source": "sources/github/owner/repo",
         "githubRepoContext": {
           "startingBranch": "main"
         }
       }
     }
     ```
   - Response: Session object with `name` field

3. **GET /sessions/{sessionId}**
   - Purpose: Get session details including PR outputs
   - Used in: `fetchJulesSession()` in loopEngine.js (line 162-171)
   - Returns session state (COMPLETED/FAILED) and outputs[].pullRequest
   - **Critical**: PR URL appears in `outputs[].pullRequest.url` AFTER session completes

4. **GET /sessions/{sessionId}/activities**
   - Purpose: List activities for a session (for status monitoring)
   - Used in: `fetchSessionActivities()` in server.js (line 297-306), `list_session_activities()` in agent.py
   - Query params: `pageSize=50`
   - Response: `{ activities: [...] }`
   - Used for: Stuck detection (status: working/stuck/success)

5. **POST /sessions/{sessionId}:sendMessage**
   - Purpose: Send a message to an existing session (for assists/continuation)
   - Used in: `sendJulesMessage()` in loopEngine.js (line 141-151), `send_message_to_session()` in agent.py
   - Request body: `{ "prompt": "message content" }`
   - Used for: Sending assist messages when session is stuck

### Multiple Agent Support
- System supports 4 Jules agents (jules-1 through jules-4)
- Each agent has its own API key: `JULES_API_KEY`, `JULES_API_KEY_2`, `JULES_API_KEY_3`, `JULES_API_KEY_4`
- Token resolution function `resolveJulesToken(agentId)` in server.js (line 287-294)

## System Architecture (from desk_agent_2.0)

### Key Components

1. **Loop Engine** (`services/loopEngine.js`)
   - Executes kanban boards as chained Jules sessions
   - Each card = one Jules session
   - Advances when PR is detected
   - Sends assist messages when stuck
   - Persists board state to JSON files

2. **Workflow Monitoring** (server.js lines 248-338)
   - Background monitoring of Jules sessions
   - SSE (Server-Sent Events) for real-time updates
   - Workflow registration via `/api/workflows`
   - Dot progress tracking via `/api/sessions/:id/dots`

3. **Hermes Agent Tools** (server.js lines 548-701)
   - Tool registration: `register_workflow()`
   - Step updates: `step_update()`
   - Cycle updates: `cycle_update()`
   - Session management: `start_jules_session()`, `list_sources()`, `list_templates()`
   - Notifications: `notify_user()`

4. **Wrapper Service** (`services/wrapperService.js`)
   - Simplifies complex Jules interactions
   - Template filling and variable substitution
   - Multi-agent token resolution

### API Endpoints (Internal Server)
- `/api/sessions/events` - SSE stream for real-time updates
- `/api/workflows` - Workflow registration/listing
- `/api/sessions/:id/dots` - Progress tracking
- `/api/hermes/tool-exec` - Tool execution (planner sidecar)
- `/api/loop/board-sync` - Kanban board synchronization

## Work State

### Completed
- ✅ Full investigation of desk_agent_2.0 Jules API usage
- ✅ Identified all 5 core Jules API endpoints
- ✅ Documented multi-agent support (4 agents)
- ✅ Understood loop engine architecture
- ✅ Identified workflow monitoring patterns
- ✅ Documented Hermes agent tool interface
- ✅ Researched CloakBrowser integration approach
- ✅ Repository exists at `/home/leon/event-scraper-github-actions`
- ✅ Created `scripts/jules_client.py` - Complete Jules API Python client
- ✅ Created `scripts/jules_cloak_scraper.py` - Jules + CloakBrowser integration
- ✅ Created `.env` with Jules API key configured
- ✅ Created `.env.example` - Environment configuration template
- ✅ Verified Jules API connection (30+ GitHub sources available)
- ✅ Created `test_jules_integration.py` - Test script for integration
- ✅ Created `QUICKSTART.md` - Quick start guide
- ✅ Created `scripts/scraper_improvement_cycle.py` - Auto-improvement with Jules AI
- ✅ Created `.github/workflows/weekly-multi-source.yml` - Main workflow
- ✅ Created `WORKFLOW_CONFIG.md` - Workflow documentation
- ✅ Repository pushed to GitHub: https://github.com/JsonLord/event-scraper-github-actions

### Active
- Repository ready for deployment

### Key Features Implemented

#### Weekly Multi-Source Scraper (Every Sunday 5 PM UTC)
**Single run, all sources in parallel:**
1. **Load Configuration** - URLs from config or manual override
2. **Scrape All Sources** - Each URL gets its own Jules session + CloakBrowser (parallel execution)
3. **Aggregate Results** - Combine all events into single `events.json`
4. **Check Completeness** - Validate each source had successful scrape
5. **Auto-Improve** - Create PRs for failed/empty sources with Jules AI improvements
6. **Deploy** - Update GitHub Pages with aggregated events

**Timing:** ~90 minutes for all sources (parallel execution, max 120 min per source)

#### Workflow Architecture
```
Sunday 17:00 UTC
    │
    ├──► Source 1: Jules Session + CloakBrowser ──┐
    ├──► Source 2: Jules Session + CloakBrowser ──┼──► Aggregate
    ├──► Source 3: Jules Session + CloakBrowser ──┼───────┐
    └──► Source N: Jules Session + CloakBrowser ──┘       │
                                                          ▼
                        Completeness Check per Source ────┼──► Improve Failed
                                                          │      Create PRs
                                                          ▼
                                                Deploy to GitHub Pages
```

#### Auto-Improvement Logic
For sources with 0 events:
- Jules AI analyzes why the scrape failed
- Generates **general improvements** (not specific fixes)
- Creates GitHub PR with improved scraper
- Next Sunday's run uses the improved scraper

### Repository Status
**URL:** https://github.com/JsonLord/event-scraper-github-actions

**Next Step:** Add repository secret:
- Name: `JULES_API_KEY`
- Value: `AQ.Ab8RN6LQcmHr0uAN-tTt74QT9xWhWsC2c0hFaJbqqTP2SjLI-g`

## Created Files

### `scripts/jules_client.py`
Complete Jules API client with:
- `JulesClient` class supporting all 4 agents (jules-1 through jules-4)
- Methods: `list_sources()`, `create_session()`, `get_session()`, `list_activities()`, `send_message()`
- Helper: `wait_for_session()` for polling session completion
- Convenience functions for simple usage
- CLI interface for testing

### `scripts/jules_cloak_scraper.py`
Integration script combining:
- Jules API for scraper logic generation
- CloakBrowser for stealth web scraping
- `EventScraper` class with human-like browsing
- `JulesEventScraper` orchestrator
- Command-line interface with options for agent selection, price filtering, date ranges

### `.env.example`
Environment template with:
- Jules API keys (JULES_API_KEY, JULES_API_KEY_2-4)
- GitHub token (GITHUB_TOKEN)
- CloakBrowser license (optional)
- Proxy configuration (optional)
- Event scraper settings (price max, date range, categories)

## CloakBrowser Integration Details

### Installation
```bash
pip install cloakbrowser
```

### Basic API (Drop-in Playwright replacement)
```python
from cloakbrowser import launch

browser = launch()
page = browser.new_page()
page.goto("https://example.com")
# ... scrape content ...
browser.close()
```

### Key Features for Event Scraping
- **Stealth**: Passes Cloudflare Turnstile, reCAPTCHA v3 (0.9 score), FingerprintJS
- **Human-like behavior**: `humanize=True` for realistic mouse/keyboard/scroll
- **Proxy support**: `proxy="http://user:pass@proxy:8080"` with residential IPs
- **Persistent profiles**: `launch_persistent_context("./profile")` for session persistence
- **Auto-downloads binary**: ~200MB Chromium binary with 66 C++ stealth patches

### Recommended Configuration for Event Sites
```python
browser = launch(
    proxy="http://residential-proxy:port",  # Residential IP not datacenter
    geoip=True,       # Match timezone + locale to proxy IP
    headless=False,   # Some sites detect headless even with patches
    humanize=True,    # Human-like interactions
)
```

### CLI Commands
```bash
python -m cloakbrowser install      # Pre-download binary
python -m cloakbrowser info         # Diagnostics
python -m cloakbrowser clear-cache  # Clear cached binaries
```

## Implementation Plan

### Phase 1: Repository Setup (Current State)
- ✅ Repository exists at `/home/leon/event-scraper-github-actions`
- ✅ Basic structure with workflows, scripts, and README
- ✅ CloakBrowser library cloned locally
- Need to: Add Jules API integration scripts and .env configuration

### Phase 2: Jules API Integration
Create Python client for Jules API endpoints:
```python
# scripts/jules_client.py
import requests
import os

JULES_API_BASE = "https://jules.googleapis.com/v1alpha"

def get_api_key(agent_id="jules-1"):
    """Get Jules API key from environment based on agent_id"""
    key_var = f"JULES_API_KEY_{agent_id.split('-')[1]}" if agent_id != "jules-1" else "JULES_API_KEY"
    return os.environ.get(key_var)

def list_sources(agent_id="jules-1"):
    """List available GitHub sources connected to Jules"""
    api_key = get_api_key(agent_id)
    response = requests.get(
        f"{JULES_API_BASE}/sources",
        headers={"X-Goog-Api-Key": api_key}
    )
    return response.json()

def create_session(agent_id="jules-1", source_id=None, prompt=None, title=None, branch="main"):
    """Create a new Jules session"""
    api_key = get_api_key(agent_id)
    payload = {
        "title": title or "Event Scraper Session",
        "prompt": prompt,
        "automationMode": "AUTO_CREATE_PR",
        "sourceContext": {
            "source": source_id,
            "githubRepoContext": {"startingBranch": branch}
        }
    }
    response = requests.post(
        f"{JULES_API_BASE}/sessions",
        headers={"X-Goog-Api-Key": api_key, "Content-Type": "application/json"},
        json=payload
    )
    return response.json()

def get_session(session_id, agent_id="jules-1"):
    """Get session details including PR outputs"""
    api_key = get_api_key(agent_id)
    response = requests.get(
        f"{JULES_API_BASE}/sessions/{session_id}",
        headers={"X-Goog-Api-Key": api_key}
    )
    return response.json()

def list_activities(session_id, agent_id="jules-1", page_size=50):
    """List session activities"""
    api_key = get_api_key(agent_id)
    response = requests.get(
        f"{JULES_API_BASE}/sessions/{session_id}/activities?pageSize={page_size}",
        headers={"X-Goog-Api-Key": api_key}
    )
    return response.json()

def send_message(session_id, message, agent_id="jules-1"):
    """Send a message to an existing session"""
    api_key = get_api_key(agent_id)
    response = requests.post(
        f"{JULES_API_BASE}/sessions/{session_id}:sendMessage",
        headers={"X-Goog-Api-Key": api_key, "Content-Type": "application/json"},
        json={"prompt": message}
    )
    return response.json()
```

### Phase 3: Environment Configuration
Create `.env.example` file:
```bash
# Jules API Configuration
JULES_API_KEY=your_jules_api_key_here
JULES_API_KEY_2=optional_second_key
JULES_API_KEY_3=optional_third_key
JULES_API_KEY_4=optional_fourth_key

# GitHub Configuration (for repository operations)
GITHUB_TOKEN=your_github_token_here

# CloakBrowser Configuration (optional)
CLOAKBROWSER_LICENSE_KEY=optional_pro_license
CLOAKBROWSER_PROXY=http://residential-proxy:port

# Event Scraper Configuration
EVENT_PRICE_MAX=15
EVENT_DATE_RANGE_DAYS=14
```

### Phase 4: Integration Scripts
1. **scripts/jules_event_scraper.py** - Main scraper using Jules + CloakBrowser
2. **scripts/.env** - User-provided Jules API credentials (gitignored)
3. Update GitHub Actions workflows to use Jules instead of Firecrawl placeholder

### Phase 5: GitHub Actions Setup
Update workflows to:
- Load .env file from repository secrets
- Install CloakBrowser (`pip install cloakbrowser`)
- Run scrapers with Jules API integration
- Deploy results to GitHub Pages

## Relevant Files
- `/home/leon/development/desk_agent_2.0/jules_agent_client/agent.py`: Core Jules API client reference
- `/home/leon/development/desk_agent_2.0/server.js`: Express server with workflow monitoring
- `/home/leon/development/desk_agent_2.0/services/loopEngine.js`: Loop engine for workflow execution
- `/home/leon/development/desk_agent_2.0/services/wrapperService.js`: Jules interaction wrapper
- `/home/leon/event-scraper-github-actions/`: Target repository for integration
- https://github.com/CloakHQ/cloakbrowser: CloakBrowser stealth browser library