"""Saved reviews (history), company coding rules, and the code quality leaderboard.

- Each review is saved in the same SQLite database. The code, file name and findings
  are encrypted, and any secrets in the code are replaced by **** before saving.
- People see only their own history. Admins see everyone's scores on the dashboard
  leaderboard, but not other people's code.
- Every review and tool use is written to the Activity Log (without the code).
"""

import json

from core.database import connect, create_tables
from modules.codereview.checks import DEFAULT_RULES, NAMING_STYLES
from modules.codereview.languages import label
from modules.codereview.security import redact
from modules.security.activity import get_setting, log_activity, raise_alert, set_setting
from modules.security.crypto import decrypt, encrypt


def create_review_tables() -> None:
    create_tables()
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS code_reviews (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL REFERENCES users(id),
                language    TEXT NOT NULL,
                file_name   TEXT,                 -- encrypted
                code        TEXT NOT NULL,        -- encrypted, secrets replaced by ****
                findings    TEXT NOT NULL,        -- encrypted JSON
                lines       INTEGER NOT NULL,
                score       REAL NOT NULL,
                critical    INTEGER NOT NULL DEFAULT 0,
                warnings    INTEGER NOT NULL DEFAULT 0,
                suggestions INTEGER NOT NULL DEFAULT 0,
                secrets     INTEGER NOT NULL DEFAULT 0,
                ai_used     INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


# ---------- Company coding rules ----------
def get_rules() -> dict:
    try:
        saved = json.loads(get_setting("code_rules", "{}"))
    except json.JSONDecodeError:
        saved = {}
    return {**DEFAULT_RULES, **{k: v for k, v in saved.items() if k in DEFAULT_RULES}}


def save_rules(admin: dict, rules: dict) -> str | None:
    """Save the company rules (admins only). Returns a problem, or None if saved."""
    if admin["role"] != "admin":
        raise PermissionError("Only admins can change the coding rules.")
    if rules.get("naming") not in NAMING_STYLES:
        return "Choose a naming style."
    try:
        function_lines = int(rules.get("max_function_lines") or 0)
        line_length = int(rules.get("max_line_length") or 0)
    except (TypeError, ValueError):
        return "The limits must be whole numbers."
    if not (0 <= function_lines <= 1000 and 0 <= line_length <= 500):
        return "Use a function limit between 0 and 1000 lines and a line limit between 0 and 500 characters."
    custom = str(rules.get("custom") or "").strip()
    if len(custom) > 2000:
        return "Keep the extra rules under 2000 characters."
    clean = {"naming": rules["naming"], "no_print": bool(rules.get("no_print")),
             "max_function_lines": function_lines, "max_line_length": line_length,
             "require_docstrings": bool(rules.get("require_docstrings")), "custom": custom}
    set_setting(admin, "code_rules", json.dumps(clean))  # also written to the Activity Log
    return None


# ---------- History ----------
def save_review(user: dict, code: str, filename: str | None, result: dict) -> int:
    """Save a finished review, record it in the Activity Log, and warn the admin about secrets."""
    create_review_tables()
    counts, secrets = result["counts"], result.get("secrets") or []
    with connect() as db:
        cursor = db.execute(
            """INSERT INTO code_reviews (user_id, language, file_name, code, findings, lines, score,
                                         critical, warnings, suggestions, secrets, ai_used)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user["id"], result["language"], encrypt(filename) if filename else None,
             encrypt(redact(code, secrets)), encrypt(json.dumps(result["findings"])), code.count("\n") + 1,
             result["score"], counts["critical"], counts["warning"], counts["suggestion"], len(secrets),
             int(result.get("ai_ok", False))))
        review_id = cursor.lastrowid
    what = filename or "pasted code"
    log_activity(user, "code_review", f"{label(result['language'])} · {what} · {code.count(chr(10)) + 1} lines · "
                                      f"score {result['score']:g}/10 · {counts['critical']} critical")
    if secrets:
        kinds = ", ".join(sorted({s["kind"] for s in secrets}))
        log_activity(user, "secret_in_code", f"{len(secrets)} secret(s) in {what}: {kinds}", level="warning")
        raise_alert("secret_in_code", user["username"],
                    f"{user['full_name']} reviewed code with {len(secrets)} secret(s) in it ({kinds}). "
                    "They were warned; the secrets were hidden and not saved.", "warning")
    return review_id


def log_tool(user: dict, tool: str, language: str) -> None:
    log_activity(user, "code_tool", f"{tool} · {label(language)}")


def _row(row) -> dict:
    review = dict(row)
    review["file_name"] = decrypt(review["file_name"]) if review["file_name"] else None
    return review


def my_reviews(user: dict, limit: int = 100) -> list[dict]:
    """Your own past reviews, newest first (without the code)."""
    create_review_tables()
    with connect() as db:
        rows = db.execute("""SELECT id, language, file_name, lines, score, critical, warnings, suggestions, secrets,
                                    ai_used, created_at FROM code_reviews WHERE user_id = ?
                             ORDER BY id DESC LIMIT ?""", (user["id"], limit)).fetchall()
    return [_row(r) for r in rows]


def get_review(user: dict, review_id: int) -> dict:
    """One of your reviews, with its code and findings. Nobody else can open it, admins included."""
    create_review_tables()
    with connect() as db:
        row = db.execute("SELECT * FROM code_reviews WHERE id = ?", (review_id,)).fetchone()
    if row is None or row["user_id"] != user["id"]:
        raise PermissionError("You can only open your own reviews.")
    review = _row(row)
    review["code"] = decrypt(review["code"])
    review["findings"] = json.loads(decrypt(review["findings"]))
    return review


def delete_review(user: dict, review_id: int) -> None:
    get_review(user, review_id)  # checks it's yours
    with connect() as db:
        db.execute("DELETE FROM code_reviews WHERE id = ? AND user_id = ?", (review_id, user["id"]))
    log_activity(user, "code_review", f"Deleted review #{review_id}")


# ---------- Leaderboard (manager dashboard) ----------
def leaderboard(days: int | None = None, limit: int = 15) -> list[dict]:
    """Average review score per person, best first. Needs at least one review in the period."""
    create_review_tables()
    since = "AND r.created_at >= datetime('now', ?)" if days else ""
    params = (f"-{days} days",) if days else ()
    with connect() as db:
        rows = db.execute(
            f"""SELECT u.id, u.full_name, u.department, COUNT(*) AS reviews, AVG(r.score) AS average,
                       MAX(r.score) AS best, SUM(r.critical) AS critical, SUM(r.secrets) AS secrets
                FROM code_reviews r JOIN users u ON u.id = r.user_id
                WHERE 1=1 {since} GROUP BY u.id ORDER BY average DESC, reviews DESC LIMIT ?""",
            (*params, limit)).fetchall()
        result = []
        for r in rows:
            scores = [s["score"] for s in db.execute(
                f"SELECT r.score FROM code_reviews r WHERE r.user_id = ? {since} ORDER BY r.id",
                (r["id"], *params))]
            result.append({"name": r["full_name"], "department": r["department"], "reviews": r["reviews"],
                           "average": round(r["average"], 1), "best": r["best"], "critical": r["critical"],
                           "secrets": r["secrets"], "first": scores[0], "latest": scores[-1],
                           "change": round(scores[-1] - scores[0], 1) if len(scores) > 1 else None})
    return result


def review_totals(days: int | None = None) -> dict:
    create_review_tables()
    since = "WHERE created_at >= datetime('now', ?)" if days else ""
    params = (f"-{days} days",) if days else ()
    with connect() as db:
        row = db.execute(f"SELECT COUNT(*) AS n, AVG(score) AS avg, SUM(secrets) AS secrets FROM code_reviews {since}",
                         params).fetchone()
    return {"reviews": row["n"] or 0, "average": round(row["avg"], 1) if row["avg"] is not None else None,
            "secrets": row["secrets"] or 0}
