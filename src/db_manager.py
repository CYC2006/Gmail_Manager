import sqlite3
import json
from datetime import datetime, timezone, timedelta

DB_NAME = "email_cache.db"


# initialize database and run one-time startup cleanup
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS analyzed_emails (
                email_id       TEXT PRIMARY KEY,
                sender         TEXT,
                receive_time   TEXT,
                category       TEXT,
                summary        TEXT,
                event_time     TEXT,
                action_required TEXT,
                last_seen      TEXT
            )
        ''')

    # purge entries not seen in any fetch for over 30 days
    cleanup_old_entries(days=30)


# check if the current mail has been analyzed
def get_cached_result(email_id):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM analyzed_emails WHERE email_id = ?', (email_id,))
        row = cursor.fetchone()

    if row:
        # refresh last_seen — this email is still present in inbox
        _touch_last_seen(email_id)
        return {
            "email_id":       row[0],
            "sender":         row[1],
            "time":           row[2],
            "category":       row[3],
            "summary":        row[4],
            "event_time":     row[5],
            "action_required":row[6],
        }
    return None


# update last_seen timestamp for an email (called whenever a cache hit occurs)
def _touch_last_seen(email_id):
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            'UPDATE analyzed_emails SET last_seen = ? WHERE email_id = ?',
            (now, email_id)
        )


# delete a single email from the cache (called when user archives or trashes)
def delete_analysis(email_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute('DELETE FROM analyzed_emails WHERE email_id = ?', (email_id,))


# delete entries not seen in any inbox fetch for more than `days` days
# emails still in inbox refresh last_seen on every fetch, so they are never deleted
# emails deleted via Gmail web stop refreshing → age out after `days` days
def cleanup_old_entries(days=30):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        # delete rows where last_seen is missing or too old
        cursor.execute(
            'DELETE FROM analyzed_emails WHERE last_seen IS NULL OR last_seen < ?',
            (cutoff,)
        )
        deleted = cursor.rowcount

    if deleted:
        print(f"[DB] Cleaned up {deleted} entries not seen for over {days} days")


# update only the summary field for an already-stored email
def update_summary(email_id, summary):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            'UPDATE analyzed_emails SET summary = ? WHERE email_id = ?',
            (summary, email_id)
        )


# save ai analyzed result into database
def save_analysis(email_id, ai_result):
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute('''
            INSERT OR REPLACE INTO analyzed_emails
            (email_id, sender, receive_time, category, summary, event_time, action_required, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            email_id,
            ai_result.get("sender"),
            ai_result.get("time"),
            ai_result.get("category"),
            ai_result.get("summary"),
            ai_result.get("event_time"),
            ai_result.get("action_required"),
            now,
        ))
