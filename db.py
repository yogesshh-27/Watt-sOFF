"""
db.py — SQLite database helpers for Watt's Off Electricity Theft Detection.

Provides connection factory, schema initialization, and safe database resets.
"""

import sqlite3
import os

IS_VERCEL = os.environ.get('VERCEL', '') == '1' or os.environ.get('VERCEL_ENV', '') != ''
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

if IS_VERCEL:
    DB_PATH = '/tmp/wattsoff.db'
else:
    DB_PATH = os.path.join(PROJECT_DIR, 'wattsoff.db')

SCHEMA_PATH = os.path.join(PROJECT_DIR, 'schema.sql')


def get_db(db_path=None):
    """
    Returns a new SQLite connection with row_factory set to sqlite3.Row
    so query results can be accessed by column name.
    """
    path = db_path or DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path=None):
    """
    Creates all tables from schema.sql if they don't already exist.
    Safe to call multiple times.
    """
    conn = get_db(db_path)
    with open(SCHEMA_PATH, 'r') as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()
    print(f"[db] Database initialized at {db_path or DB_PATH}")


def reset_db(db_path=None):
    """
    Drops and recreates the database. If locked on Windows, drops and recreates all tables.
    """
    path = db_path or DB_PATH
    if os.path.exists(path):
        try:
            os.remove(path)
            print(f"[db] Removed existing database: {path}")
        except Exception:
            conn = get_db(db_path)
            conn.execute("PRAGMA foreign_keys = OFF")
            cursor = conn.cursor()
            tables = [row[0] for row in cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
            for t in tables:
                conn.execute(f"DROP TABLE IF EXISTS {t}")
            conn.commit()
            conn.close()
            print(f"[db] Dropped existing tables (file in use): {path}")
    init_db(db_path)


if __name__ == '__main__':
    init_db()
