"""Helpdesk logic: create tickets, list them, change their status and add replies.

Tickets live in the same SQLite database as the users (data/officemind.db).
"""

from datetime import datetime, timezone

from core.config import TICKET_CATEGORIES
from core.database import connect, create_tables
from modules.security.crypto import decrypt, encrypt, is_encrypted

# The three steps a ticket goes through. Saved in the database as the key,
# shown on screen as the label.
STATUSES = {
    "open": "Open",
    "in_progress": "In Progress",
    "closed": "Closed",
}

# How urgent a ticket is. The AI suggests one; the employee can change it.
URGENCIES = {
    "high": "High",
    "medium": "Medium",
    "low": "Low",
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
                urgency     TEXT NOT NULL DEFAULT 'medium',
                ai_urgency  TEXT,
                created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # Databases made before Phase 2, Step 2 don't have the urgency columns yet: add them.
        # Older tickets simply become "medium".
        columns = {row["name"] for row in db.execute("PRAGMA table_info(tickets)")}
        if "urgency" not in columns:
            db.execute("ALTER TABLE tickets ADD COLUMN urgency TEXT NOT NULL DEFAULT 'medium'")
        if "ai_urgency" not in columns:
            db.execute("ALTER TABLE tickets ADD COLUMN ai_urgency TEXT")
        # Phase 4 (Dashboard) needs to know when a ticket was closed.
        # Tickets closed before this existed use their last update time as the best guess.
        if "closed_at" not in columns:
            db.execute("ALTER TABLE tickets ADD COLUMN closed_at TEXT")
            db.execute("UPDATE tickets SET closed_at = updated_at WHERE status = 'closed'")
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
        # Security: encrypt ticket text saved before encryption existed (runs once per row)
        for row in db.execute("SELECT id, title, description FROM tickets WHERE title NOT LIKE 'enc:v1:%' OR description NOT LIKE 'enc:v1:%'").fetchall():
            if not is_encrypted(row["title"]) or not is_encrypted(row["description"]):
                db.execute("UPDATE tickets SET title = ?, description = ? WHERE id = ?",
                           (encrypt(row["title"]), encrypt(row["description"]), row["id"]))
        for row in db.execute("SELECT id, message FROM ticket_replies WHERE message NOT LIKE 'enc:v1:%'").fetchall():
            if not is_encrypted(row["message"]):
                db.execute("UPDATE ticket_replies SET message = ? WHERE id = ?",
                           (encrypt(row["message"]), row["id"]))


def _decrypt_ticket(row) -> dict:
    """A ticket row with its title and description readable again."""
    ticket = dict(row)
    for field in ("title", "description"):
        if field in ticket:
            ticket[field] = decrypt(ticket[field])
    return ticket


def _require_admin(user: dict) -> None:
    """Stop right here if someone who is not an admin tries an admin action."""
    if user["role"] != "admin":
        raise PermissionError("Only admins can do this.")


# ---------- Employees ----------
def check_ticket_text(title: str, description: str) -> str | None:
    """Returns an error message if the title or description isn't OK, otherwise None."""
    title = title.strip()
    description = description.strip()
    if len(title) < 3:
        return "Please give the ticket a short title (at least 3 characters)."
    if len(title) > MAX_TITLE_LENGTH:
        return f"The title can be at most {MAX_TITLE_LENGTH} characters."
    if not description:
        return "Please describe the problem."
    if len(description) > MAX_TEXT_LENGTH:
        return f"The description can be at most {MAX_TEXT_LENGTH} characters."
    return None


def create_ticket(
    user: dict,
    title: str,
    description: str,
    category: str,
    urgency: str = "medium",
    ai_urgency: str | None = None,
) -> tuple[int | None, str | None]:
    """Save a new ticket. Returns (ticket number, None) or (None, error message).

    `urgency` is what the employee finally chose; `ai_urgency` is what the AI suggested."""
    error = check_ticket_text(title, description)
    if error:
        return None, error
    if category not in TICKET_CATEGORIES:
        return None, "Please choose a category."
    if urgency not in URGENCIES:
        return None, "Please choose an urgency."
    if ai_urgency not in (None, *URGENCIES):
        ai_urgency = None

    create_helpdesk_tables()
    with connect() as db:
        cursor = db.execute(
            """
            INSERT INTO tickets (user_id, title, description, category, urgency, ai_urgency)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user["id"], encrypt(title.strip()), encrypt(description.strip()), category, urgency, ai_urgency),
        )
    return cursor.lastrowid, None


def list_tickets(user: dict) -> list[dict]:
    """Admins get every ticket; employees only get their own.

    Order: tickets still being worked on come before Closed ones. Inside each group:
    High urgency first, then Medium, then Low; then Open before In Progress; newest first."""
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
        ORDER BY CASE tickets.status WHEN 'closed' THEN 1 ELSE 0 END,
                 CASE tickets.urgency WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                 CASE tickets.status WHEN 'open' THEN 0 ELSE 1 END,
                 tickets.id DESC
    """
    with connect() as db:
        return [_decrypt_ticket(row) for row in db.execute(query, params)]


# ---------- For the helpdesk AI ----------
def active_tickets() -> list[dict]:
    """Every ticket that is still Open or In Progress (from all employees)."""
    create_helpdesk_tables()
    with connect() as db:
        rows = db.execute(
            "SELECT id, title, description, status FROM tickets WHERE status != 'closed'"
        )
        return [_decrypt_ticket(row) for row in rows]


def solved_tickets() -> list[dict]:
    """Closed tickets that have at least one admin reply, with those replies joined together.
    These are the "past solutions" the AI can learn a fix from."""
    create_helpdesk_tables()
    with connect() as db:
        rows = db.execute(
            """
            SELECT tickets.id, tickets.title, tickets.description, ticket_replies.message
            FROM tickets
            JOIN ticket_replies ON ticket_replies.ticket_id = tickets.id
            JOIN users ON users.id = ticket_replies.user_id
            WHERE tickets.status = 'closed' AND users.role = 'admin'
            ORDER BY tickets.id, ticket_replies.id
            """
        ).fetchall()
    # The replies are encrypted, so they're joined together here rather than in SQL
    solved: dict[int, dict] = {}
    for row in rows:
        ticket = solved.setdefault(row["id"], {**_decrypt_ticket(row), "replies": []})
        ticket["replies"].append(decrypt(row["message"]))
    for ticket in solved.values():
        ticket["solution"] = " / ".join(ticket.pop("replies"))
        ticket.pop("message", None)
    return list(solved.values())


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
        return [{**dict(row), "message": decrypt(row["message"])} for row in rows]


# ---------- Admins ----------
def update_status(admin: dict, ticket_id: int, status: str) -> None:
    """Move a ticket to Open, In Progress or Closed."""
    _require_admin(admin)
    if status not in STATUSES:
        raise ValueError(f"Unknown status: {status}")
    with connect() as db:
        # closed_at: set when the ticket is closed, cleared if it is opened again
        db.execute(
            """
            UPDATE tickets
            SET status = ?, updated_at = CURRENT_TIMESTAMP,
                closed_at = CASE WHEN ? = 'closed'
                                 THEN COALESCE(CASE WHEN status = 'closed' THEN closed_at END,
                                               CURRENT_TIMESTAMP)
                                 ELSE NULL END
            WHERE id = ?
            """,
            (status, status, ticket_id),
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
            (ticket_id, admin["id"], encrypt(message)),
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
