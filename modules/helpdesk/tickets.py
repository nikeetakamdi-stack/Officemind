"""Helpdesk logic: create tickets, list them, change their status and add replies.

Tickets live in the same SQLite database as the users (data/officemind.db).
"""

from datetime import datetime, timezone

from core.config import TICKET_CATEGORIES
from core.database import connect, create_tables

# The three steps a ticket goes through. Saved in the database as the key,
# shown on screen as the label.
STATUSES = {
    "open": "Open",
    "in_progress": "In Progress",
    "closed": "Closed",
}

MAX_TITLE_LENGTH = 120
MAX_TEXT_LENGTH = 4000


def create_helpdesk_tables() -> None:
    """Create the ticket tables the first time they are needed. Safe to call every time."""
    create_tables()  # makes sure the users table exists first
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS tickets (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL REFERENCES users(id),
                title       TEXT NOT NULL,
                description TEXT NOT NULL,
                category    TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'open'
                            CHECK (status IN ('open', 'in_progress', 'closed')),
                created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS ticket_replies (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id  INTEGER NOT NULL REFERENCES tickets(id),
                user_id    INTEGER NOT NULL REFERENCES users(id),
                message    TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def _require_admin(user: dict) -> None:
    """Stop right here if someone who is not an admin tries an admin action."""
    if user["role"] != "admin":
        raise PermissionError("Only admins can do this.")


# ---------- Employees ----------
def create_ticket(
    user: dict, title: str, description: str, category: str
) -> tuple[int | None, str | None]:
    """Save a new ticket. Returns (ticket number, None) or (None, error message)."""
    title = title.strip()
    description = description.strip()

    if len(title) < 3:
        return None, "Please give the ticket a short title (at least 3 characters)."
    if len(title) > MAX_TITLE_LENGTH:
        return None, f"The title can be at most {MAX_TITLE_LENGTH} characters."
    if not description:
        return None, "Please describe the problem."
    if len(description) > MAX_TEXT_LENGTH:
        return None, f"The description can be at most {MAX_TEXT_LENGTH} characters."
    if category not in TICKET_CATEGORIES:
        return None, "Please choose a category."

    create_helpdesk_tables()
    with connect() as db:
        cursor = db.execute(
            "INSERT INTO tickets (user_id, title, description, category) VALUES (?, ?, ?, ?)",
            (user["id"], title, description, category),
        )
    return cursor.lastrowid, None


def list_tickets(user: dict) -> list[dict]:
    """Admins get every ticket; employees only get their own.

    Order: Open first, then In Progress, then Closed; newest first inside each group."""
    create_helpdesk_tables()
    query = """
        SELECT tickets.*, users.full_name AS author,
               (SELECT COUNT(*) FROM ticket_replies WHERE ticket_id = tickets.id) AS reply_count
        FROM tickets JOIN users ON users.id = tickets.user_id
    """
    params: tuple = ()
    if user["role"] != "admin":
        query += " WHERE tickets.user_id = ?"
        params = (user["id"],)
    query += """
        ORDER BY CASE tickets.status WHEN 'open' THEN 0 WHEN 'in_progress' THEN 1 ELSE 2 END,
                 tickets.id DESC
    """
    with connect() as db:
        return [dict(row) for row in db.execute(query, params)]


def list_replies(ticket_id: int) -> list[dict]:
    """All replies on one ticket, oldest first, with the writer's name and role."""
    create_helpdesk_tables()
    with connect() as db:
        rows = db.execute(
            """
            SELECT ticket_replies.*, users.full_name AS author, users.role AS author_role
            FROM ticket_replies JOIN users ON users.id = ticket_replies.user_id
            WHERE ticket_id = ?
            ORDER BY ticket_replies.id
            """,
            (ticket_id,),
        )
        return [dict(row) for row in rows]


# ---------- Admins ----------
def update_status(admin: dict, ticket_id: int, status: str) -> None:
    """Move a ticket to Open, In Progress or Closed."""
    _require_admin(admin)
    if status not in STATUSES:
        raise ValueError(f"Unknown status: {status}")
    with connect() as db:
        db.execute(
            "UPDATE tickets SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, ticket_id),
        )


def add_reply(admin: dict, ticket_id: int, message: str) -> str | None:
    """Add a reply or note to a ticket. Returns an error message, or None if it worked."""
    _require_admin(admin)
    message = message.strip()
    if not message:
        return "The reply is empty."
    if len(message) > MAX_TEXT_LENGTH:
        return f"A reply can be at most {MAX_TEXT_LENGTH} characters."
    with connect() as db:
        db.execute(
            "INSERT INTO ticket_replies (ticket_id, user_id, message) VALUES (?, ?, ?)",
            (ticket_id, admin["id"], message),
        )
        db.execute(
            "UPDATE tickets SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (ticket_id,)
        )
    return None


# ---------- Helpers ----------
def friendly_time(timestamp: str) -> str:
    """'2026-11-27 06:53:45' (saved in UTC) -> '27 Nov 2026, 12:23' in your own time zone."""
    moment = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return moment.astimezone().strftime("%d %b %Y, %H:%M")
