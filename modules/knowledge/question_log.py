"""Remembers every question asked to the AI assistant, and whether it could answer.

The Dashboard uses this to show the most-asked questions, and the questions the AI
couldn't answer (so the admin knows which documents to add).
"""

import re

from core.database import connect, create_tables
from modules.security.crypto import encrypt, is_encrypted


def create_question_table() -> None:
    create_tables()
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_questions (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id  INTEGER REFERENCES users(id),
                question TEXT NOT NULL,
                answered INTEGER NOT NULL,          -- 1 = answered from documents, 0 = not
                page     TEXT NOT NULL,             -- where it was asked, e.g. "knowledge"
                asked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # Security: encrypt questions saved before encryption existed
        for row in db.execute("SELECT id, question FROM ai_questions WHERE question NOT LIKE 'enc:v1:%'").fetchall():
            if not is_encrypted(row["question"]):
                db.execute("UPDATE ai_questions SET question = ? WHERE id = ?",
                           (encrypt(row["question"]), row["id"]))


def normalize(question: str) -> str:
    """Make small differences disappear, so "How many leave days?" and
    "how many leave days" count as the same question."""
    text = re.sub(r"[^\w\s]", " ", question.lower())
    return " ".join(text.split())


def log_question(user: dict | None, question: str, answered: bool, page: str) -> None:
    """Save one question. Never let logging break the chat."""
    try:
        create_question_table()
        with connect() as db:
            db.execute(
                "INSERT INTO ai_questions (user_id, question, answered, page) VALUES (?, ?, ?, ?)",
                (user["id"] if user else None, encrypt(question.strip()[:500]), int(answered), page),
            )
    except Exception:
        pass
