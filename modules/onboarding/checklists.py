"""Onboarding logic: checklists, tasks, assigning them to new employees, and progress.

Everything is stored in the same SQLite database as users and tickets.
"""

from datetime import datetime, timezone

from core.config import ONBOARDING_STUCK_DAYS
from core.database import connect, create_tables

MAX_NAME_LENGTH = 80
MAX_TITLE_LENGTH = 120
MAX_DESCRIPTION_LENGTH = 1000

# How each employee is doing, shown in the admin's progress table
STATUSES = {
    "completed": "Completed",
    "on_track": "On track",
    "not_started": "Not started",
    "stuck": "Stuck",
}


def create_onboarding_tables() -> None:
    """Create the four onboarding tables the first time. Safe to call every time."""
    create_tables()  # makes sure the users table exists first
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS checklists (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                created_by  INTEGER NOT NULL REFERENCES users(id),
                created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS checklist_tasks (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                checklist_id INTEGER NOT NULL REFERENCES checklists(id),
                position     INTEGER NOT NULL,
                title        TEXT NOT NULL,
                description  TEXT NOT NULL DEFAULT '',
                document     TEXT  -- name of an uploaded PDF, or NULL
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS onboarding_assignments (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                checklist_id INTEGER NOT NULL REFERENCES checklists(id),
                user_id      INTEGER NOT NULL REFERENCES users(id),
                assigned_by  INTEGER NOT NULL REFERENCES users(id),
                assigned_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (checklist_id, user_id)
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS task_progress (
                assignment_id INTEGER NOT NULL REFERENCES onboarding_assignments(id),
                task_id       INTEGER NOT NULL REFERENCES checklist_tasks(id),
                done_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (assignment_id, task_id)
            )
            """
        )


def _require_admin(user: dict) -> None:
    """Stop right here if someone who is not an admin tries an admin action."""
    if user["role"] != "admin":
        raise PermissionError("Only admins can do this.")


def _days_since(timestamp: str) -> int:
    """Whole days between a saved time (UTC) and now."""
    moment = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - moment).days


def days_ago_text(days: int) -> str:
    return "today" if days == 0 else "yesterday" if days == 1 else f"{days} days ago"


# ---------- Admin: checklists and tasks ----------
def create_checklist(admin: dict, name: str, description: str) -> tuple[int | None, str | None]:
    """Returns (checklist id, None) or (None, error message)."""
    _require_admin(admin)
    name, description = name.strip(), description.strip()
    if len(name) < 3:
        return None, "Please give the checklist a name (at least 3 characters)."
    if len(name) > MAX_NAME_LENGTH:
        return None, f"The name can be at most {MAX_NAME_LENGTH} characters."
    if len(description) > MAX_DESCRIPTION_LENGTH:
        return None, f"The description can be at most {MAX_DESCRIPTION_LENGTH} characters."
    create_onboarding_tables()
    with connect() as db:
        cursor = db.execute(
            "INSERT INTO checklists (name, description, created_by) VALUES (?, ?, ?)",
            (name, description, admin["id"]),
        )
    return cursor.lastrowid, None


def delete_checklist(admin: dict, checklist_id: int) -> None:
    """Delete a checklist with its tasks, assignments and everyone's progress on it."""
    _require_admin(admin)
    with connect() as db:
        db.execute(
            """DELETE FROM task_progress WHERE assignment_id IN
               (SELECT id FROM onboarding_assignments WHERE checklist_id = ?)""",
            (checklist_id,),
        )
        db.execute("DELETE FROM onboarding_assignments WHERE checklist_id = ?", (checklist_id,))
        db.execute("DELETE FROM checklist_tasks WHERE checklist_id = ?", (checklist_id,))
        db.execute("DELETE FROM checklists WHERE id = ?", (checklist_id,))


def add_task(
    admin: dict, checklist_id: int, title: str, description: str, document: str | None = None
) -> str | None:
    """Add a task at the end of a checklist. Returns an error message, or None if it worked."""
    _require_admin(admin)
    title, description = title.strip(), description.strip()
    if len(title) < 3:
        return "Please give the task a title (at least 3 characters)."
    if len(title) > MAX_TITLE_LENGTH:
        return f"The title can be at most {MAX_TITLE_LENGTH} characters."
    if len(description) > MAX_DESCRIPTION_LENGTH:
        return f"The description can be at most {MAX_DESCRIPTION_LENGTH} characters."
    with connect() as db:
        position = db.execute(
            "SELECT COALESCE(MAX(position), 0) + 1 FROM checklist_tasks WHERE checklist_id = ?",
            (checklist_id,),
        ).fetchone()[0]
        db.execute(
            """INSERT INTO checklist_tasks (checklist_id, position, title, description, document)
               VALUES (?, ?, ?, ?, ?)""",
            (checklist_id, position, title, description, document or None),
        )
    return None


def delete_task(admin: dict, task_id: int) -> None:
    _require_admin(admin)
    with connect() as db:
        db.execute("DELETE FROM task_progress WHERE task_id = ?", (task_id,))
        db.execute("DELETE FROM checklist_tasks WHERE id = ?", (task_id,))


def list_checklists() -> list[dict]:
    """Every checklist with how many tasks it has and how many people it's assigned to."""
    create_onboarding_tables()
    with connect() as db:
        rows = db.execute(
            """
            SELECT checklists.*,
                   (SELECT COUNT(*) FROM checklist_tasks WHERE checklist_id = checklists.id) AS task_count,
                   (SELECT COUNT(*) FROM onboarding_assignments WHERE checklist_id = checklists.id) AS assigned_count
            FROM checklists ORDER BY checklists.id
            """
        )
        return [dict(row) for row in rows]


def list_tasks(checklist_id: int) -> list[dict]:
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM checklist_tasks WHERE checklist_id = ? ORDER BY position", (checklist_id,)
        )
        return [dict(row) for row in rows]


# ---------- Admin: assigning ----------
def list_employees() -> list[dict]:
    """Everyone with the employee role, A to Z."""
    create_tables()
    with connect() as db:
        rows = db.execute(
            "SELECT id, username, full_name FROM users WHERE role = 'employee' ORDER BY full_name"
        )
        return [dict(row) for row in rows]


def assigned_user_ids(checklist_id: int) -> set[int]:
    with connect() as db:
        rows = db.execute(
            "SELECT user_id FROM onboarding_assignments WHERE checklist_id = ?", (checklist_id,)
        )
        return {row["user_id"] for row in rows}


def assign_checklist(admin: dict, checklist_id: int, user_ids: list[int]) -> int:
    """Give a checklist to employees. Returns how many new assignments were made
    (someone who already has this checklist is skipped)."""
    _require_admin(admin)
    with connect() as db:
        before = db.total_changes
        db.executemany(
            """INSERT OR IGNORE INTO onboarding_assignments (checklist_id, user_id, assigned_by)
               VALUES (?, ?, ?)""",
            [(checklist_id, user_id, admin["id"]) for user_id in user_ids],
        )
        return db.total_changes - before


# ---------- Admin: progress overview ----------
def progress_overview(admin: dict) -> list[dict]:
    """One row per (employee, checklist) with progress and a status.

    "Stuck" = not finished and nothing ticked for ONBOARDING_STUCK_DAYS days
    (counted from the last ticked task, or from the day it was assigned)."""
    _require_admin(admin)
    create_onboarding_tables()
    with connect() as db:
        rows = db.execute(
            """
            SELECT a.id AS assignment_id, u.full_name AS employee, u.username,
                   c.name AS checklist, a.assigned_at,
                   (SELECT COUNT(*) FROM checklist_tasks t WHERE t.checklist_id = c.id) AS total,
                   (SELECT COUNT(*) FROM task_progress p
                      JOIN checklist_tasks t ON t.id = p.task_id
                      WHERE p.assignment_id = a.id) AS done,
                   (SELECT MAX(done_at) FROM task_progress p WHERE p.assignment_id = a.id) AS last_done
            FROM onboarding_assignments a
            JOIN users u ON u.id = a.user_id
            JOIN checklists c ON c.id = a.checklist_id
            ORDER BY u.full_name, c.name
            """
        )
        overview = [dict(row) for row in rows]

    for row in overview:
        last_activity = row["last_done"] or row["assigned_at"]
        row["days_idle"] = _days_since(last_activity)
        row["percent"] = round(100 * row["done"] / row["total"]) if row["total"] else 0
        if row["total"] and row["done"] == row["total"]:
            row["status"] = "completed"
        elif row["days_idle"] >= ONBOARDING_STUCK_DAYS:
            row["status"] = "stuck"
        elif row["done"] == 0:
            row["status"] = "not_started"
        else:
            row["status"] = "on_track"
    return overview


# ---------- Employees ----------
def my_onboarding(user: dict) -> list[dict]:
    """The checklists assigned to this user, each with its tasks marked done or not."""
    create_onboarding_tables()
    with connect() as db:
        assignments = [
            dict(row)
            for row in db.execute(
                """
                SELECT a.id, a.checklist_id, c.name, c.description
                FROM onboarding_assignments a JOIN checklists c ON c.id = a.checklist_id
                WHERE a.user_id = ? ORDER BY a.id
                """,
                (user["id"],),
            )
        ]
        for assignment in assignments:
            tasks = db.execute(
                """
                SELECT t.*, p.done_at
                FROM checklist_tasks t
                LEFT JOIN task_progress p ON p.task_id = t.id AND p.assignment_id = ?
                WHERE t.checklist_id = ? ORDER BY t.position
                """,
                (assignment["id"], assignment["checklist_id"]),
            )
            assignment["tasks"] = [{**dict(t), "done": t["done_at"] is not None} for t in tasks]
            assignment["total"] = len(assignment["tasks"])
            assignment["done"] = sum(t["done"] for t in assignment["tasks"])
    return assignments


def set_task_done(user: dict, assignment_id: int, task_id: int, done: bool) -> bool:
    """Tick or untick a task. Only works on the user's own checklist.
    Returns True if this made the whole checklist complete."""
    with connect() as db:
        assignment = db.execute(
            "SELECT * FROM onboarding_assignments WHERE id = ? AND user_id = ?",
            (assignment_id, user["id"]),
        ).fetchone()
        if assignment is None:
            raise PermissionError("This checklist isn't yours.")
        task = db.execute(
            "SELECT id FROM checklist_tasks WHERE id = ? AND checklist_id = ?",
            (task_id, assignment["checklist_id"]),
        ).fetchone()
        if task is None:
            raise ValueError("This task isn't on your checklist.")

        if done:
            db.execute(
                "INSERT OR IGNORE INTO task_progress (assignment_id, task_id) VALUES (?, ?)",
                (assignment_id, task_id),
            )
        else:
            db.execute(
                "DELETE FROM task_progress WHERE assignment_id = ? AND task_id = ?",
                (assignment_id, task_id),
            )

        total, finished = db.execute(
            """
            SELECT (SELECT COUNT(*) FROM checklist_tasks WHERE checklist_id = ?),
                   (SELECT COUNT(*) FROM task_progress WHERE assignment_id = ?)
            """,
            (assignment["checklist_id"], assignment_id),
        ).fetchone()
    return done and total > 0 and finished == total
