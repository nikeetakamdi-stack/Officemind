"""Quick stats for the home page, different for admins and employees."""

from core.database import connect
from modules.helpdesk.tickets import create_helpdesk_tables
from modules.knowledge.question_log import create_question_table
from modules.onboarding.checklists import my_onboarding, progress_overview


def _documents() -> int:
    try:
        from modules.knowledge.assistant import list_documents
        return len(list_documents())
    except Exception:
        return 0


def home_stats(user: dict) -> list[dict]:
    """Four stat cards: [{"icon", "label", "value", "note", "tone"}]."""
    create_helpdesk_tables()
    create_question_table()
    documents = _documents()

    if user["role"] == "admin":
        with connect() as db:
            open_count, high = db.execute(
                """SELECT COALESCE(SUM(status != 'closed'), 0),
                          COALESCE(SUM(status != 'closed' AND urgency = 'high'), 0) FROM tickets"""
            ).fetchone()
        rows = progress_overview(user)
        onboarding = len({r["username"] for r in rows if r["status"] != "completed"})
        stuck = sum(r["status"] == "stuck" for r in rows)
        return [
            {"icon": "confirmation_number", "label": "Open tickets", "value": open_count,
             "note": "waiting or in progress", "tone": "amber" if open_count else "green"},
            {"icon": "priority_high", "label": "High urgency", "value": high,
             "note": "open tickets", "tone": "red" if high else "green"},
            {"icon": "group", "label": "Onboarding", "value": onboarding,
             "note": f"{stuck} stuck" if stuck else "employees in progress"},
            {"icon": "description", "label": "Documents", "value": documents, "note": "in the knowledge base"},
        ]

    with connect() as db:
        mine_open = db.execute(
            "SELECT COUNT(*) FROM tickets WHERE user_id = ? AND status != 'closed'", (user["id"],)
        ).fetchone()[0]
        asked = db.execute(
            "SELECT COUNT(*) FROM ai_questions WHERE user_id = ? AND asked_at >= datetime('now', '-7 days')",
            (user["id"],),
        ).fetchone()[0]
    assignments = my_onboarding(user)
    done = sum(a["done"] for a in assignments)
    total = sum(a["total"] for a in assignments)
    return [
        {"icon": "confirmation_number", "label": "My open tickets", "value": mine_open,
         "note": "waiting or in progress"},
        {"icon": "task_alt", "label": "Onboarding", "value": f"{done}/{total}" if total else "—",
         "note": f"{round(100 * done / total)}% done" if total else "no checklist yet",
         "tone": "green" if total and done == total else "brand"},
        {"icon": "description", "label": "Documents", "value": documents, "note": "you can ask about"},
        {"icon": "forum", "label": "Questions asked", "value": asked, "note": "this week"},
    ]
