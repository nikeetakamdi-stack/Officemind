"""Dashboard numbers: everything the manager dashboard shows, worked out from the database.

`days` is the date filter: 7, 30, or None for "all time".
Ticket and question numbers follow the filter. Documents and onboarding show "right now".
"""

import io
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from modules.security.crypto import decrypt

from core.config import TICKET_CATEGORIES
from core.database import connect
from modules.helpdesk.tickets import STATUSES, URGENCIES, create_helpdesk_tables
from modules.knowledge.assistant import list_documents
from modules.knowledge.question_log import create_question_table, normalize
from modules.onboarding.checklists import STATUSES as ONBOARDING_STATUSES
from modules.onboarding.checklists import progress_overview

RANGES = {"7": ("Last 7 days", 7), "30": ("Last 30 days", 30), "all": ("All time", None)}


def _since(column: str, days: int | None) -> tuple[str, tuple]:
    """A piece of SQL that keeps only rows from the last `days` days (or everything)."""
    if days is None:
        return "", ()
    return f" AND {column} >= datetime('now', ?)", (f"-{days} days",)


def _prepare() -> None:
    create_helpdesk_tables()
    create_question_table()


# ---------- Stat cards ----------
def ticket_stats(days: int | None) -> dict:
    """Total tickets, open tickets (not closed yet) and average hours to close, in the range."""
    _prepare()
    where, params = _since("created_at", days)
    closed_where, closed_params = _since("closed_at", days)
    with connect() as db:
        total, still_open = db.execute(
            f"""SELECT COUNT(*), COALESCE(SUM(status != 'closed'), 0)
                FROM tickets WHERE 1=1{where}""",
            params,
        ).fetchone()
        avg_hours, closed = db.execute(
            f"""SELECT AVG((julianday(closed_at) - julianday(created_at)) * 24), COUNT(*)
                FROM tickets WHERE status = 'closed' AND closed_at IS NOT NULL{closed_where}""",
            closed_params,
        ).fetchone()
    return {"total": total, "open": still_open, "avg_close_hours": avg_hours, "closed": closed}


def format_duration(hours: float | None) -> str:
    """3.5 -> '3.5 h', 50 -> '2.1 days', 0.2 -> '12 min', None -> '—'."""
    if hours is None:
        return "—"
    if hours < 1:
        return f"{max(1, round(hours * 60))} min"
    if hours < 48:
        return f"{hours:.1f} h"
    return f"{hours / 24:.1f} days"


def document_count() -> int:
    try:
        return len(list_documents())
    except Exception:
        return 0


def onboarding_now(admin: dict) -> list[dict]:
    """Everyone's onboarding progress right now (same rows as the Onboarding page)."""
    return progress_overview(admin)


def employees_onboarding(rows: list[dict]) -> int:
    """How many different employees still have an unfinished checklist."""
    return len({r["username"] for r in rows if r["status"] != "completed"})


# ---------- Charts ----------
def tickets_by_category(days: int | None) -> list[tuple[str, int]]:
    """Every category (even with 0 tickets), in the usual order."""
    _prepare()
    where, params = _since("created_at", days)
    with connect() as db:
        counts = dict(
            db.execute(
                f"SELECT category, COUNT(*) FROM tickets WHERE 1=1{where} GROUP BY category", params
            ).fetchall()
        )
    return [(category, counts.get(category, 0)) for category in TICKET_CATEGORIES]


def tickets_by_urgency(days: int | None) -> list[tuple[str, int]]:
    """[("high", n), ("medium", n), ("low", n)]."""
    _prepare()
    where, params = _since("created_at", days)
    with connect() as db:
        counts = dict(
            db.execute(
                f"SELECT urgency, COUNT(*) FROM tickets WHERE 1=1{where} GROUP BY urgency", params
            ).fetchall()
        )
    return [(key, counts.get(key, 0)) for key in URGENCIES]


def tickets_over_time(days: int | None) -> tuple[list[tuple[date, int]], str]:
    """New tickets per day (or per week when "all time" covers more than 60 days).
    Days without tickets are included as 0, so the line doesn't skip them.
    Returns (points, "day" or "week")."""
    _prepare()
    where, params = _since("created_at", days)
    with connect() as db:
        rows = db.execute(
            f"SELECT date(created_at), COUNT(*) FROM tickets WHERE 1=1{where} GROUP BY 1", params
        ).fetchall()
    per_day = {date.fromisoformat(day): count for day, count in rows}

    today = datetime.now(timezone.utc).date()
    if days is not None:
        start = today - timedelta(days=days - 1)
    else:
        start = min(per_day, default=today)
    span = (today - start).days + 1

    if days is None and span > 60:
        per_week: dict[date, int] = defaultdict(int)
        for day, count in per_day.items():
            per_week[day - timedelta(days=day.weekday())] += count  # Monday of that week
        first = start - timedelta(days=start.weekday())
        weeks = [first + timedelta(weeks=i) for i in range((today - first).days // 7 + 1)]
        return [(week, per_week.get(week, 0)) for week in weeks], "week"

    return [(start + timedelta(days=i), per_day.get(start + timedelta(days=i), 0)) for i in range(span)], "day"


# ---------- AI questions ----------
def _questions(days: int | None) -> list[dict]:
    _prepare()
    where, params = _since("asked_at", days)
    with connect() as db:
        rows = db.execute(
            f"SELECT question, answered, asked_at FROM ai_questions WHERE 1=1{where} ORDER BY id",
            params,
        )
        return [{**dict(row), "question": decrypt(row["question"])} for row in rows]


def _group(questions: list[dict]) -> list[dict]:
    """Group questions that are the same apart from capitals and punctuation."""
    groups: dict[str, dict] = {}
    for q in questions:
        key = normalize(q["question"])
        if not key:
            continue
        group = groups.setdefault(key, {"question": q["question"], "times": 0, "answered": 0, "last_asked": q["asked_at"]})
        group["question"] = q["question"]  # show the latest wording
        group["times"] += 1
        group["answered"] += q["answered"]
        group["last_asked"] = q["asked_at"]
    return list(groups.values())


def top_questions(days: int | None, limit: int = 8) -> list[dict]:
    """Most-asked questions first: {"question", "times", "answered", "last_asked"}."""
    groups = _group(_questions(days))
    return sorted(groups, key=lambda g: (g["times"], g["last_asked"]), reverse=True)[:limit]


def unanswered_questions(days: int | None, limit: int = 15) -> list[dict]:
    """Questions the AI couldn't answer from the documents, most frequent first."""
    unanswered = [q for q in _questions(days) if not q["answered"]]
    groups = _group(unanswered)
    return sorted(groups, key=lambda g: (g["times"], g["last_asked"]), reverse=True)[:limit]


def question_count(days: int | None) -> tuple[int, int]:
    """(questions asked, of which answered)."""
    questions = _questions(days)
    return len(questions), sum(q["answered"] for q in questions)


# ---------- Excel export ----------
def _all_tickets(days: int | None) -> list[dict]:
    _prepare()
    where, params = _since("tickets.created_at", days)
    with connect() as db:
        rows = db.execute(
            f"""
            SELECT tickets.id AS "Ticket", tickets.title AS "Title", tickets.category AS "Category",
                   tickets.urgency AS "Urgency", tickets.status AS "Status",
                   users.full_name AS "Raised by", tickets.created_at AS "Created (UTC)",
                   tickets.closed_at AS "Closed (UTC)"
            FROM tickets JOIN users ON users.id = tickets.user_id
            WHERE 1=1{where} ORDER BY tickets.id
            """,
            params,
        )
        tickets = [dict(row) for row in rows]
    for t in tickets:
        t["Title"] = decrypt(t["Title"])
        t["Urgency"] = URGENCIES.get(t["Urgency"], t["Urgency"])
        t["Status"] = STATUSES.get(t["Status"], t["Status"])
    return tickets


def excel_report(admin: dict, days: int | None, range_label: str) -> bytes:
    """One Excel file with a sheet for each part of the dashboard. Admins only."""
    if admin.get("role") != "admin":
        raise PermissionError("Only admins can export data.")
    from modules.security.activity import log_activity
    log_activity(admin, "export", f"Dashboard Excel · {range_label}")
    stats = ticket_stats(days)
    onboarding = onboarding_now(admin)
    asked, answered = question_count(days)
    summary = [
        ("Date range", range_label),
        ("Created", datetime.now().strftime("%d %b %Y, %H:%M")),
        ("Total tickets", stats["total"]),
        ("Open tickets", stats["open"]),
        ("Average time to close", format_duration(stats["avg_close_hours"])),
        ("Tickets closed", stats["closed"]),
        ("Documents in knowledge base", document_count()),
        ("Employees onboarding", employees_onboarding(onboarding)),
        ("Questions asked to the AI", asked),
        ("Questions answered from documents", answered),
    ]
    points, unit = tickets_over_time(days)
    sheets = {
        "Summary": pd.DataFrame(summary, columns=["Measure", "Value"]),
        "Tickets": pd.DataFrame(_all_tickets(days)),
        "By category": pd.DataFrame(tickets_by_category(days), columns=["Category", "Tickets"]),
        "By urgency": pd.DataFrame(
            [(URGENCIES[k], n) for k, n in tickets_by_urgency(days)], columns=["Urgency", "Tickets"]
        ),
        "Over time": pd.DataFrame(points, columns=["Day" if unit == "day" else "Week starting", "New tickets"]),
        "Onboarding": pd.DataFrame(
            [
                {
                    "Employee": r["employee"], "Checklist": r["checklist"],
                    "Done": r["done"], "Total": r["total"], "Progress %": r["percent"],
                    "Days since last activity": r["days_idle"],
                    "Status": ONBOARDING_STATUSES[r["status"]],
                }
                for r in onboarding
            ]
        ),
        "Top questions": pd.DataFrame(
            [
                {"Question": q["question"], "Times asked": q["times"], "Answered": q["answered"],
                 "Last asked (UTC)": q["last_asked"]}
                for q in top_questions(days, limit=50)
            ]
        ),
        "Unanswered": pd.DataFrame(
            [
                {"Question": q["question"], "Times asked": q["times"], "Last asked (UTC)": q["last_asked"]}
                for q in unanswered_questions(days, limit=200)
            ]
        ),
    }

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, frame in sheets.items():
            if frame.empty:
                frame = pd.DataFrame({"": ["No data for this period"]})
            frame.to_excel(writer, sheet_name=name, index=False)
            sheet = writer.sheets[name]
            # Make each column wide enough to read
            for column in sheet.columns:
                longest = max(len(str(cell.value or "")) for cell in column)
                sheet.column_dimensions[column[0].column_letter].width = min(max(12, longest + 2), 60)
            sheet.freeze_panes = "A2"
    return buffer.getvalue()
