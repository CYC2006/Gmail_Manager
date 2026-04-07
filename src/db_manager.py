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