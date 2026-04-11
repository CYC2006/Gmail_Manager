import sqlite3
import json

DB_NAME = "email_cache.db"


# initialize database
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS analyzed_emails (
                email_id TEXT PRIMARY KEY,
                sender TEXT,
                receive_time TEXT,
                category TEXT,
                summary TEXT,
                event_time TEXT,
                action_required TEXT
            )
        ''')


# check if the current mail has been analyzed
def get_cached_result(email_id):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM analyzed_emails WHERE email_id = ?', (email_id,))
        row = cursor.fetchone()
    
    if row:
        return {
            "email_id": row[0],
            "sender": row[1],
            "time": row[2],
            "category": row[3],
            "summary": row[4],
            "event_time": row[5],
            "action_required": row[6]
        }
    return None


# delete a single email from the cache (called when user archives or trashes)
def delete_analysis(email_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute('DELETE FROM analyzed_emails WHERE email_id = ?', (email_id,))


# remove DB entries whose email_id is no longer in the provided inbox id set
def remove_stale_emails(current_inbox_ids: set):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT email_id FROM analyzed_emails')
        stored_ids = {row[0] for row in cursor.fetchall()}
        stale_ids = stored_ids - current_inbox_ids
        if stale_ids:
            conn.executemany('DELETE FROM analyzed_emails WHERE email_id = ?',
                             [(eid,) for eid in stale_ids])
            print(f"[DB] Removed {len(stale_ids)} stale entries from cache")


# update only the summary field for an already-stored email
def update_summary(email_id, summary):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute('UPDATE analyzed_emails SET summary = ? WHERE email_id = ?', (summary, email_id))


# save ai analyzed result into database
def save_analysis(email_id, ai_result):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO analyzed_emails 
            (email_id, sender, receive_time, category, summary, event_time, action_required)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            email_id,
            ai_result.get("sender"),
            ai_result.get("time"),
            ai_result.get("category"),
            ai_result.get("summary"),
            ai_result.get("event_time"),
            ai_result.get("action_required")
        ))