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
