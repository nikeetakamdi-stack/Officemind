"""The notification bell: short "things that need your attention" messages.

Nothing new is stored: everything is worked out from tickets, onboarding and
AI questions that are already in the database.
"""

from core.database import connect
from modules.security.crypto import decrypt
from modules.helpdesk.tickets import create_helpdesk_tables
from modules.knowledge.question_log import create_question_table
from modules.onboarding.checklists import my_onboarding, progress_overview

HELPDESK = "pages/2_Helpdesk.py"
ONBOARDING = "pages/3_Onboarding.py"
DASHBOARD = "pages/4_Dashboard.py"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def notifications_for(user: dict) -> list[dict]:
    """[{"icon", "text", "page"}, ...], most important first. Never breaks the page."""
    try:
        return _admin(user) if user["role"] == "admin" else _employee(user)
    except Exception:
        return []


def _admin(admin: dict) -> list[dict]:
    create_helpdesk_tables()
    create_question_table()
    with connect() as db:
        high = db.execute(
            "SELECT COUNT(*) FROM tickets WHERE status != 'closed' AND urgency = 'high'"
        ).fetchone()[0]
        waiting = db.execute("SELECT COUNT(*) FROM tickets WHERE status = 'open'").fetchone()[0]
        unanswered = db.execute(
            "SELECT COUNT(*) FROM ai_questions WHERE answered = 0 AND asked_at >= datetime('now', '-7 days')"
        ).fetchone()[0]
    stuck = sum(r["status"] == "stuck" for r in progress_overview(admin))

    from modules.security.activity import open_alert_count
    alerts = open_alert_count()
    items = []
    if alerts:
        items.append({"icon": "notification_important",
                      "text": f"{_plural(alerts, 'security alert')} to review", "page": "pages/6_Security.py"})
    if high:
        items.append({"icon": "priority_high", "text": f"{_plural(high, 'high-urgency ticket')} open", "page": HELPDESK})
    if waiting:
        items.append({"icon": "confirmation_number", "text": f"{_plural(waiting, 'ticket')} waiting to be picked up", "page": HELPDESK})
    if stuck:
        items.append({"icon": "hourglass_empty", "text": f"{_plural(stuck, 'employee')} stuck in onboarding", "page": ONBOARDING})
    if unanswered:
        items.append({"icon": "help", "text": f"{_plural(unanswered, 'question')} the AI couldn't answer this week", "page": DASHBOARD})
    return items


def _employee(user: dict) -> list[dict]:
    create_helpdesk_tables()
    with connect() as db:
        replies = db.execute(
            """
            SELECT t.id, t.title FROM tickets t
            JOIN ticket_replies r ON r.ticket_id = t.id
            JOIN users u ON u.id = r.user_id
            WHERE t.user_id = ? AND u.role = 'admin' AND r.created_at >= datetime('now', '-7 days')
            GROUP BY t.id ORDER BY MAX(r.created_at) DESC LIMIT 5
            """,
            (user["id"],),
        ).fetchall()
        closed = db.execute(
            """SELECT id, title FROM tickets WHERE user_id = ? AND status = 'closed'
               AND closed_at >= datetime('now', '-7 days') ORDER BY closed_at DESC LIMIT 5""",
            (user["id"],),
        ).fetchall()

    items = [{"icon": "forum", "text": f"New reply on #{r['id']} {decrypt(r['title'])}", "page": HELPDESK}
             for r in replies]
    items += [{"icon": "task_alt", "text": f"#{r['id']} {decrypt(r['title'])} was closed", "page": HELPDESK}
              for r in closed]
    left = sum(a["total"] - a["done"] for a in my_onboarding(user))
    if left:
        items.append({"icon": "checklist", "text": f"{_plural(left, 'onboarding task')} left", "page": ONBOARDING})
    return items
