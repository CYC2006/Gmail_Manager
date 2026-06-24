# NCKU AInbox

A Gmail client for NCKU students that automatically categorizes emails with AI, extracts assignment deadlines to a visual calendar, and highlights announcements matching the student's major and interests.

Available as both a **web app** (Flask) and a **desktop app** (Flet).

---

## Features

- **AI-powered categorization** — Groq LLM (Llama 3.3 70B) classifies every email into school-relevant categories (作業死線, 停課通知, 考試時間, Moodle 通知, 一般宣導, 講座活動, 其他)
- **Smart calendar** — Automatically extracts dates from Moodle and deadline emails and displays them in a monthly calendar view; supports manually created events
- **Preference matching** — Highlights 講座活動 / 一般宣導 emails whose content matches your declared major and interests
- **Real-time streaming** — Web app uses Server-Sent Events (SSE) so emails appear as they are analyzed
- **Multi-key Groq support** — Register up to 5 API keys with automatic fallback when a daily token limit is hit
- **Local SQLite cache** — Analyzed results are cached so re-opening the app is instant; AI is only called for new emails
- **Inbox actions** — Mark as read, star, archive, restore, or trash emails directly from the UI
- **AI detail analysis** — Click any email to get a structured summary, action items, key dates, and related links

---

## File Structure

```
Gmail_Manager/
│
├── run_gui.py                    # Desktop app entry point (Flet)
├── run_cli.py                    # Legacy CLI entry point
├── requirements.txt              # Python dependencies
├── credentials.json              # Gmail OAuth2 client credentials (not in VCS)
├── token.json                    # Cached Gmail OAuth2 token (not in VCS)
│
├── web/                          # Web app (Flask + vanilla JS)
│   ├── app.py                    # Flask server — REST API + SSE streaming
│   ├── templates/
│   │   └── index.html            # Single-page app shell
│   └── static/
│       ├── css/main.css          # Stylesheet (dark/light/system themes)
│       └── js/app.js             # Frontend logic (views, modals, calendar, settings)
│
├── src/
│   ├── ai_agent.py               # Groq calls: categorize, extract events, detail analysis
│   ├── gmail_reader.py           # Gmail API: authenticate, fetch, batch-analyze emails
│   ├── email_parser.py           # Email body extraction and HTML-to-text conversion
│   ├── email_actions.py          # Gmail API actions: read, star, archive, trash
│   ├── db_manager.py             # SQLite cache for analyzed emails (email_cache.db)
│   ├── calendar_db.py            # SQLite store for extracted calendar events
│   ├── calendar_view.py          # Calendar UI builder (desktop app only)
│   ├── config_manager.py         # Read/write API keys and user preferences to JSON
│   ├── preference_matcher.py     # Keyword matching: email text vs. user major/interests
│   ├── categories.py             # Category label constants
│   │
│   ├── settings/
│   │   ├── api_keys.py           # Settings tab UI — manage and verify Groq API keys (desktop)
│   │   ├── preference.py         # Settings tab UI — major selector and interest chips (desktop)
│   │   ├── account.py            # Settings tab UI — user profile form (desktop)
│   │   ├── preference_options.json  # Available majors and interest labels
│   │   └── __init__.py
│   │
│   └── prompts/
│       ├── email_categorize.txt      # System prompt for general email categorization
│       ├── moodle_categorize.txt     # System prompt for Moodle email categorization
│       ├── email_detail_analyze.txt  # Prompt for full structured email analysis
│       └── moodle_event_extract.txt  # Prompt for extracting deadline/event times
│
└── data/                         # Runtime data (auto-created, not in VCS)
    ├── config.json               # Saved verified Groq API keys
    ├── user_preferences.json     # Saved major and interest selections
    ├── web_settings.json         # Web app theme preference
    ├── email_cache.db            # SQLite: analyzed_emails table
    └── calendar_events.db        # SQLite: calendar_events table
```

---

## Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.11+ |
| Gmail account | NCKU Google Workspace or personal Gmail |
| Groq API key | Free tier at [console.groq.com](https://console.groq.com) |

---

## Installation

### 1. Clone the repository

```bash
git clone <repo-url>
cd Gmail_Manager
```

### 2. Create and activate a virtual environment

```bash
python -m venv venv
source venv/bin/activate        # macOS / Linux
venv\Scripts\activate           # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Set up Gmail OAuth credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/) and create a project.
2. Enable the **Gmail API** for the project.
3. Create **OAuth 2.0 Client ID** credentials (Desktop app type).
4. Download the credentials file and save it as `credentials.json` in the project root.

The first time you launch the app, a browser window will open for you to authorize Gmail access. A `token.json` file is then created automatically for future sessions.

---

## Usage

### Web app (recommended)

```bash
python web/app.py
```

Then open [http://localhost:5001](http://localhost:5001) in your browser.

The web app exposes a REST + SSE API:

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/emails/stream?view=inbox` | SSE stream — yields emails as JSON as they are analyzed |
| `GET` | `/api/email/<id>/body` | Fetch raw email body |
| `GET` | `/api/email/<id>/analyze` | AI detail analysis (cached) |
| `POST` | `/api/email/<id>/star` | Toggle star |
| `POST` | `/api/email/<id>/archive` | Archive |
| `POST` | `/api/email/<id>/trash` | Move to trash |
| `POST` | `/api/email/<id>/restore` | Restore from trash |
| `POST` | `/api/email/<id>/delete` | Permanently delete |
| `GET/POST` | `/api/calendar/events` | List or create calendar events |
| `DELETE` | `/api/calendar/events/<id>` | Delete a calendar event |
| `GET/POST` | `/api/settings/profile` | User profile (name, gender, major) |
| `GET/POST` | `/api/settings/interests` | Interest tags |
| `GET/POST` | `/api/settings/api-keys` | Groq API keys |
| `GET/POST` | `/api/settings/theme` | Dark / light / system theme |

### Desktop app (Flet)

```bash
python run_gui.py
```

### CLI (legacy)

```bash
python run_cli.py
```

---

## Configuration

### Adding Groq API Keys

**Web:** Open Settings → API Keys, enter keys, click **Save & Verify**.

**Desktop:** Open the **設定** tab → **API Keys** sub-tab, enter keys, click **驗證並儲存**.

Keys are stored locally in `data/config.json`. The app automatically switches to the next key if the daily token limit for the current key is reached.

### Setting Preferences (Major & Interests)

**Web:** Open Settings → Preference. Toggle interest chips and select your major.

**Desktop:** Open **設定 → 偏好設定**, select your **主修科系** and toggle **興趣標籤**.

Changes take effect immediately — matching emails are highlighted on the next sync.

---

## How It Works

```
Gmail API
    └─▶ fetch_and_analyze_emails()          # gmail_reader.py
            ├─▶ [cache hit]  yield immediately from SQLite
            └─▶ [cache miss] categorize_email()    # ai_agent.py → Groq
                    ├─▶ save_analysis()             # db_manager.py
                    ├─▶ extract_moodle_events()     # ai_agent.py (Moodle only)
                    │       └─▶ add_event()         # calendar_db.py
                    └─▶ match_preferences()         # preference_matcher.py
```

1. On sync, the app fetches the latest emails from Gmail in batches of 10 (up to 500 total).
2. Emails already in the local cache are displayed instantly.
3. New emails are sent to Groq for categorization (rate-limited to 30 RPM).
4. Moodle emails additionally undergo event extraction; found dates are added to the calendar.
5. 講座活動 / 一般宣導 emails are checked against your saved preferences for keyword highlighting.
6. Clicking an email card triggers a deeper AI analysis (summary, action items, key URLs, key dates).

---

## Data & Privacy

All data stays on your local machine:

- Emails are fetched via OAuth2 — no credentials are ever sent to third parties.
- Email bodies are sent to the **Groq API** for AI analysis only (subject to [Groq's privacy policy](https://groq.com/privacy-policy/)).
- Cached results, preferences, and API keys are stored in the `data/` directory.

---

## Development Notes

- **`web/app.py`** and **`run_gui.py`** share the same `src/` backend — AI, Gmail, DB, and settings modules are reused as-is.
- The SSE endpoint in the web app (`/api/emails/stream`) mirrors the generator-based `fetch_and_analyze_emails()` used by the desktop app; clients split the stream into Inbox / Moodle / All Mail views on the frontend.
- **Rate limiting** in `ai_agent.py` enforces a minimum 2.5 s gap between Groq calls to stay within the 30 RPM free-tier limit.
- The two-pass fetch strategy in `gmail_reader.py` (cached emails first, then AI queue) ensures the UI populates immediately while background categorization continues.

---

## License

This project is for educational and personal productivity use. Not affiliated with NCKU or Google.
