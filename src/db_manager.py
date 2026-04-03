import sqlite3
import json

DB_NAME = "email_cache.db"

def init_db():
    """初始化資料庫與資料表"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # 建立表格，使用 email_id 作為主鍵
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
    conn.commit()
    conn.close()

def get_cached_result(email_id):
    """查詢信件是否已經分析過，若有則回傳字典格式的結果"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM analyzed_emails WHERE email_id = ?', (email_id,))
    row = cursor.fetchone()
    conn.close()
    
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

def save_analysis(email_id, ai_result):
    """將 AI 的分析結果存入資料庫"""
    conn = sqlite3.connect(DB_NAME)
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
    conn.commit()
    conn.close()