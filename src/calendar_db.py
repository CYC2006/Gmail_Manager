import os
import sqlite3
import uuid
from datetime import datetime, timezone

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
os.makedirs(_DATA_DIR, exist_ok=True)
CAL_DB = os.path.join(_DATA_DIR, "calendar_events.db")


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
                added_at   TEXT NOT NULL,
                color      TEXT,
                end_time   TEXT,
                is_all_day INTEGER DEFAULT 0,
                notes      TEXT
            )
        ''')
        # migrate existing DBs that predate these columns
        for col_sql in [
            'ALTER TABLE calendar_events ADD COLUMN category  TEXT',
            'ALTER TABLE calendar_events ADD COLUMN color     TEXT',
            'ALTER TABLE calendar_events ADD COLUMN end_time  TEXT',
            'ALTER TABLE calendar_events ADD COLUMN is_all_day INTEGER DEFAULT 0',
            'ALTER TABLE calendar_events ADD COLUMN notes     TEXT',
        ]:
            try:
                conn.execute(col_sql)
            except sqlite3.OperationalError:
                pass  # column already exists


def event_exists(email_id: str, event_time: str, label: str = '') -> bool:
    """Return True if (email_id, event_time) OR (label, event_time) already exists."""
    with sqlite3.connect(CAL_DB) as conn:
        cursor = conn.cursor()
        cursor.execute(
            'SELECT 1 FROM calendar_events WHERE '
            '(email_id = ? AND event_time = ?) OR (label = ? AND event_time = ?)',
            (email_id, event_time, label, event_time)
        )
        return cursor.fetchone() is not None


def add_event(email_id: str, label: str, event_time: str,
              source: str = "manual", category: str = None) -> bool:
    """Add an event to the calendar.
    Returns True if added, False if a duplicate (email_id, event_time) or (label, event_time) exists."""
    if event_exists(email_id, event_time, label):
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
            'SELECT id, email_id, label, event_time, source, category, added_at, '
            '       color, end_time, is_all_day, notes '
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
            "color":      r[7],
            "end_time":   r[8],
            "is_all_day": bool(r[9]) if r[9] is not None else False,
            "notes":      r[10],
        }
        for r in rows
    ]


def add_custom_event(date_key: str, title: str, start_time: str,
                     end_time: str, is_all_day: bool, color: str, notes: str) -> bool:
    """Add a user-created custom event.
    date_key  — 'YYYY-MM-DD' of the clicked calendar cell
    start_time — 'HH:MM' or empty string
    end_time   — 'HH:MM' or empty string
    Returns True on success."""
    event_time = date_key if (is_all_day or not start_time) else f"{date_key} {start_time}"
    now        = datetime.now(timezone.utc).isoformat()
    custom_id  = f"custom_{uuid.uuid4().hex[:12]}"
    with sqlite3.connect(CAL_DB) as conn:
        conn.execute(
            'INSERT INTO calendar_events '
            '(email_id, label, event_time, source, category, added_at, color, end_time, is_all_day, notes) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (custom_id, title, event_time, "custom", None, now,
             color, end_time or None, int(is_all_day), notes or None)
        )
    return True


def delete_event(event_id: int):
    """Remove a calendar event by its row id."""
    with sqlite3.connect(CAL_DB) as conn:
        conn.execute('DELETE FROM calendar_events WHERE id = ?', (event_id,))


def delete_event_by_key(email_id: str, event_time: str):
    """Remove a calendar event by (email_id, event_time) pair."""
    with sqlite3.connect(CAL_DB) as conn:
        conn.execute(
            'DELETE FROM calendar_events WHERE email_id = ? AND event_time = ?',
            (email_id, event_time)
        )


def delete_events_by_email_id(email_id: str):
    """Remove all calendar events associated with an email."""
    with sqlite3.connect(CAL_DB) as conn:
        conn.execute('DELETE FROM calendar_events WHERE email_id = ?', (email_id,))
