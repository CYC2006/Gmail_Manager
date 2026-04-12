import sqlite3
from datetime import datetime, timezone

CAL_DB = "calendar_events.db"


def init_calendar_db():
    """Create the calendar_events table if it doesn't exist, and migrate existing DBs."""
    with sqlite3.connect(CAL_DB) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS calendar_events (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                email_id   TEXT NOT NULL,
                label      TEXT NOT NULL,
                event_time TEXT NOT NULL,
                source     TEXT NOT NULL DEFAULT 'manual',
                category   TEXT,
                added_at   TEXT NOT NULL
            )
        ''')
        # migrate existing DBs that predate the category column
        try:
            conn.execute('ALTER TABLE calendar_events ADD COLUMN category TEXT')
        except Exception:
            pass  # column already exists


def event_exists(email_id: str, event_time: str) -> bool:
    """Return True if this (email_id, event_time) pair is already stored."""
    with sqlite3.connect(CAL_DB) as conn:
        cursor = conn.cursor()
        cursor.execute(
            'SELECT 1 FROM calendar_events WHERE email_id = ? AND event_time = ?',
            (email_id, event_time)
        )
        return cursor.fetchone() is not None


def add_event(email_id: str, label: str, event_time: str,
              source: str = "manual", category: str = None) -> bool:
    """Add an event to the calendar.
    Returns True if added, False if the same (email_id, event_time) already exists."""
    if event_exists(email_id, event_time):
        return False
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(CAL_DB) as conn:
        conn.execute(
            'INSERT INTO calendar_events (email_id, label, event_time, source, category, added_at) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (email_id, label, event_time, source, category, now)
        )
    return True


def get_all_events() -> list:
    """Return all calendar events ordered by event_time."""
    with sqlite3.connect(CAL_DB) as conn:
        cursor = conn.cursor()
        cursor.execute(
            'SELECT id, email_id, label, event_time, source, category, added_at '
            'FROM calendar_events ORDER BY event_time'
        )
        rows = cursor.fetchall()
    return [
        {
            "id":         r[0],
            "email_id":   r[1],
            "label":      r[2],
            "event_time": r[3],
            "source":     r[4],
            "category":   r[5],
            "added_at":   r[6],
        }
        for r in rows
    ]


def delete_event(event_id: int):
    """Remove a calendar event by its row id."""
    with sqlite3.connect(CAL_DB) as conn:
        conn.execute('DELETE FROM calendar_events WHERE id = ?', (event_id,))
