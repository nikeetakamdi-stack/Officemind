"""Opens the SQLite database (one file: data/officemind.db) and creates its tables."""

import sqlite3
from contextlib import contextmanager

from core.config import DATABASE_PATH


@contextmanager
def connect():
    """Open the database, save changes when done, and always close it again.

    Use it like:  with connect() as db: db.execute(...)
    """
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATABASE_PATH)
    db.row_factory = sqlite3.Row  # lets us read columns by name, e.g. row["role"]
    try:
        with db:  # saves (commits) on success, undoes on error
            yield db
    finally:
        db.close()


def create_tables() -> None:
    """Create the tables the first time OfficeMind runs. Safe to call every time."""
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT NOT NULL UNIQUE,
                full_name     TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role          TEXT NOT NULL CHECK (role IN ('admin', 'employee')),
                created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # Security module: extra columns, added to older databases automatically
        columns = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
        new_columns = {
            "department": "TEXT NOT NULL DEFAULT 'General'",
            "clearance": "INTEGER NOT NULL DEFAULT 0",       # 1 = may see Confidential documents
            "email": "TEXT",                                  # encrypted
            "failed_attempts": "INTEGER NOT NULL DEFAULT 0",
            "locked_until": "TEXT",                           # UTC time, or NULL
        }
        for name, definition in new_columns.items():
            if name not in columns:
                db.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")
