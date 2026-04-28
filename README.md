# NCKU Gmail Manager

A desktop application that helps NCKU students manage their school Gmail inbox — automatically categorizing emails with AI, extracting assignment deadlines to a visual calendar, and surfacing announcements that match the student's major and interests.

---

## Features

- **AI-powered categorization** — Groq LLM (Llama 3.3 70B) classifies every email into school-relevant categories (作業死線, 停課通知, 考試時間, Moodle 通知, 一般宣導, 講座活動, 其他)
- **Smart calendar** — Automatically extracts dates from Moodle and deadline emails and displays them in a 14-month calendar view
- **Preference matching** — Highlights 講座活動 / 一般宣導 emails whose content matches your declared major and interests
- **Multi-key Groq support** — Register up to 5 API keys with automatic fallback when a daily token limit is hit
- **Local SQLite cache** — Analyzed results are cached so re-opening the app is instant; AI is only called for new emails
- **Inbox actions** — Mark as read, star, archive, or trash emails directly from the UI
- **Open in Gmail** — Jump to any email in the browser with one click

---

## File Structure

```
Gmail_Manager/
│
├── gui_main.py                   # Main GUI entry point (Flet desktop app)
├── main.py                       # Legacy CLI entry point
├── requirements.txt              # Python dependencies
├── credentials.json              # Gmail OAuth2 client credentials (not in VCS)
├── token.json                    # Cached Gmail OAuth2 token (not in VCS)
│
├── src/
│   ├── ai_agent.py               # Groq calls: categorize, extract events, detail analysis
│   ├── gmail_reader.py           # Gmail API: authenticate, fetch, batch-analyze emails
│   ├── email_parser.py           # Email body extraction and HTML-to-text conversion
│   ├── email_actions.py          # Gmail API actions: read, star, archive, trash
│   ├── db_manager.py             # SQLite cache for analyzed emails (email_cache.db)
│   ├── calendar_db.py            # SQLite store for extracted calendar events
│   ├── calendar_view.py          # Calendar UI builder (14-month grid with event chips)
│   ├── config_manager.py         # Read/write API keys and user preferences to JSON
│   ├── preference_matcher.py     # Keyword matching: email text vs. user major/interests
│   │
│   ├── settings/
│   │   ├── api_keys.py           # Settings tab UI — manage and verify Groq API keys
│   │   ├── preference.py         # Settings tab UI — major selector and interest chips
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

### Launch the GUI application (recommended)

```bash
python gui_main.py
```

### Launch the legacy CLI

```bash
python main.py
```

---

## Configuration

### Adding Groq API Keys

1. Open the app and click the **設定** tab.
2. Select the **API Keys** sub-tab.
3. Enter one or more Groq API keys (up to 5).
4. Click **驗證並儲存** — keys are tested against the live API before being saved.

Keys are stored locally in `data/config.json`. The app automatically switches to the next key if the daily token limit for the current key is reached.

### Setting Preferences (Major & Interests)

1. Open **設定 → 偏好設定**.
2. Select your **主修科系** from the dropdown.
3. Toggle your **興趣標籤** (e.g., 程式設計, 創業, 資安).
4. Changes take effect immediately — matching emails are highlighted on the next sync.

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

1. On sync, the app fetches the latest emails from Gmail in batches of 10.
2. Emails already in the local cache are displayed instantly.
3. New emails are sent to Groq for categorization (rate-limited to 30 RPM).
4. Moodle emails additionally undergo event extraction; found dates are added to the calendar.
5. 講座活動 / 一般宣導 emails are checked against your saved preferences for keyword highlighting.
6. Clicking an email card triggers a deeper AI analysis (summary, action items, key URLs).

---

## Data & Privacy

All data stays on your local machine:

- Emails are fetched via OAuth2 — no credentials are ever sent to third parties.
- Email bodies are sent to the **Groq API** for AI analysis only (subject to [Groq's privacy policy](https://groq.com/privacy-policy/)).
- Cached results, preferences, and API keys are stored in the `data/` directory.

---

## Development Notes

- **`gui_main.py`** is intentionally a single-module Flet app. The monolithic structure keeps Flet's closure-based state management straightforward at the current scale; splitting it is planned for a future milestone when the feature set stabilizes.
- **Rate limiting** in `ai_agent.py` enforces a minimum 2.5 s gap between Groq calls to stay within the 30 RPM free-tier limit.
- The two-pass fetch strategy in `gmail_reader.py` (cached emails first, then AI queue) ensures the UI populates immediately while background categorization continues.

---

## License

This project is for educational and personal productivity use. Not affiliated with NCKU or Google.
