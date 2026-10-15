import sqlite3
import os

# Resolves database file to the root backend/ folder
DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../ecopulse.db"))

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            source TEXT,
            item_or_event TEXT,
            status_or_category TEXT,
            impact TEXT
        )
    """)
    conn.commit()
    conn.close()