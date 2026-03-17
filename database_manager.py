import os
import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("POSTGRES_URL") # Vercel provides this

def get_db_connection():
    if DATABASE_URL:
        # Production: Postgres
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    else:
        # Local: SQLite
        conn = sqlite3.connect("coach.db")
        conn.row_factory = sqlite3.Row
        return conn

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    
    if DATABASE_URL:
        # Postgres syntax
        cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            line_user_id TEXT PRIMARY KEY,
            name TEXT,
            goal TEXT,
            persona TEXT,
            frequency TEXT,
            last_interacted_at TIMESTAMP,
            next_ping_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        cur.execute('''
        CREATE TABLE IF NOT EXISTS chat_history (
            id SERIAL PRIMARY KEY,
            line_user_id TEXT,
            role TEXT,
            message TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (line_user_id) REFERENCES users (line_user_id)
        )
        ''')
    else:
        # SQLite syntax
        cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            line_user_id TEXT PRIMARY KEY,
            name TEXT,
            goal TEXT,
            persona TEXT,
            frequency TEXT,
            last_interacted_at DATETIME,
            next_ping_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        cur.execute('''
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            line_user_id TEXT,
            role TEXT,
            message TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (line_user_id) REFERENCES users (line_user_id)
        )
        ''')
    
    conn.commit()
    cur.close()
    conn.close()

if __name__ == "__main__":
    init_db()
