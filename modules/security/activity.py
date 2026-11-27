"""Activity log, alerts and app settings.

- activity_log: who did what, and when (logins, uploads, deletions, exports, questions...).
  The details are encrypted, because they can contain questions or file names.
- security_alerts: things an admin should look at (many failed logins, a phone pointed
  at the screen, prompt tricks, repeated questions about confidential documents).
- app_settings: small on/off settings, e.g. whether Secure mode is available.
"""

from datetime import datetime, timedelta, timezone

from core.database import connect, create_tables
from modules.security.crypto import decrypt, encrypt

# What each action is called on screen, with an icon
ACTIONS = {
    "login": ("Signed in", "login"),
    "login_failed": ("Failed sign-in", "password"),
    "account_locked": ("Account locked", "lock"),
    "logout": ("Signed out", "logout"),
    "auto_logout": ("Signed out (inactive)", "timer_off"),
    "signup": ("Account created", "person_add"),
    "upload": ("Uploaded document", "upload_file"),
    "delete": ("Deleted document", "delete"),
    "access_change": ("Changed document access", "shield"),
    "export": ("Exported data", "download"),
    "ask": ("Asked the AI", "forum"),
    "blocked_prompt": ("Blocked prompt trick", "gpp_bad"),
    "confidential_probe": ("Asked about confidential content", "visibility_off"),
    "masked": ("Sensitive data masked", "masks"),
    "phone_detected": ("Phone pointed at screen", "phone_android"),
    "secure_mode": ("Secure mode", "videocam"),
    "user_change": ("Changed a user", "manage_accounts"),
    "settings": ("Changed a setting", "settings"),
    "chat_message": ("Sent a chat message", "chat"),
    "chat_file": ("Shared a file in chat", "attach_file"),
    "chat_download": ("Opened a chat file", "file_open"),
    "chat_pin": ("Pinned a message", "push_pin"),
    "channel_change": ("Changed a channel", "group"),
    "call_start": ("Started a call", "call"),
    "call_end": ("Ended a call", "call_end"),
    "code_review": ("Reviewed code", "rate_review"),
    "code_tool": ("Used a code tool", "build"),
    "secret_in_code": ("Secret found in code", "key"),
}
LEVELS = ("info", "warning", "critical")


def create_security_tables() -> None:
    create_tables()
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS activity_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER,
                username   TEXT,
                action     TEXT NOT NULL,
                details    TEXT,                 -- encrypted
                level      TEXT NOT NULL DEFAULT 'info',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS security_alerts (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                kind       TEXT NOT NULL,
                username   TEXT,
                message    TEXT NOT NULL,        -- encrypted
                level      TEXT NOT NULL DEFAULT 'warning',
                resolved   INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )


# ---------- Settings ----------
def get_setting(key: str, default: str = "") -> str:
    create_security_tables()
    with connect() as db:
        row = db.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(admin: dict, key: str, value: str) -> None:
    if admin["role"] != "admin":
        raise PermissionError("Only admins can change settings.")
    create_security_tables()
    with connect() as db:
        db.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
    log_activity(admin, "settings", f"{key} = {value}")


def secure_mode_enabled() -> bool:
    return get_setting("secure_mode_enabled", "0") == "1"


# ---------- Activity log ----------
def log_activity(user: dict | None, action: str, details: str = "", level: str = "info",
                 username: str | None = None) -> None:
    """Record one event. Never breaks the page if it fails."""
    try:
        create_security_tables()
        with connect() as db:
            db.execute(
                "INSERT INTO activity_log (user_id, username, action, details, level) VALUES (?, ?, ?, ?, ?)",
                (user["id"] if user else None, user["username"] if user else username,
                 action, encrypt(details[:1000]) if details else None, level),
            )
    except Exception:
        pass


def list_activity(days: int | None = 7, username: str | None = None, action: str | None = None,
                  limit: int = 500) -> list[dict]:
    create_security_tables()
    query = "SELECT * FROM activity_log WHERE 1=1"
    params: list = []
    if days:
        query += " AND created_at >= datetime('now', ?)"
        params.append(f"-{days} days")
    if username:
        query += " AND username = ?"
        params.append(username)
    if action:
        query += " AND action = ?"
        params.append(action)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with connect() as db:
        rows = [dict(r) for r in db.execute(query, params)]
    for row in rows:
        row["details"] = decrypt(row["details"]) or ""
    return rows


def count_recent(action: str, minutes: int, username: str | None = None) -> int:
    create_security_tables()
    query = "SELECT COUNT(*) FROM activity_log WHERE action = ? AND created_at >= datetime('now', ?)"
    params: list = [action, f"-{minutes} minutes"]
    if username:
        query += " AND username = ?"
        params.append(username)
    with connect() as db:
        return db.execute(query, params).fetchone()[0]


# ---------- Alerts ----------
def raise_alert(kind: str, username: str | None, message: str, level: str = "warning",
                dedupe_minutes: int = 30) -> bool:
    """Create an alert, unless the same kind of alert for the same user is already
    open from the last `dedupe_minutes` (so one incident doesn't flood the list)."""
    try:
        create_security_tables()
        with connect() as db:
            recent = db.execute(
                """SELECT 1 FROM security_alerts WHERE kind = ? AND COALESCE(username, '') = ?
                   AND resolved = 0 AND created_at >= datetime('now', ?)""",
                (kind, username or "", f"-{dedupe_minutes} minutes"),
            ).fetchone()
            if recent:
                return False
            db.execute(
                "INSERT INTO security_alerts (kind, username, message, level) VALUES (?, ?, ?, ?)",
                (kind, username, encrypt(message), level),
            )
        return True
    except Exception:
        return False


def list_alerts(include_resolved: bool = False, limit: int = 200) -> list[dict]:
    create_security_tables()
    query = "SELECT * FROM security_alerts"
    if not include_resolved:
        query += " WHERE resolved = 0"
    query += " ORDER BY resolved, id DESC LIMIT ?"
    with connect() as db:
        rows = [dict(r) for r in db.execute(query, (limit,))]
    for row in rows:
        row["message"] = decrypt(row["message"])
    return rows


def resolve_alert(admin: dict, alert_id: int) -> None:
    if admin["role"] != "admin":
        raise PermissionError("Only admins can resolve alerts.")
    with connect() as db:
        db.execute("UPDATE security_alerts SET resolved = 1 WHERE id = ?", (alert_id,))
    log_activity(admin, "settings", f"Resolved alert #{alert_id}")


def open_alert_count() -> int:
    create_security_tables()
    with connect() as db:
        return db.execute("SELECT COUNT(*) FROM security_alerts WHERE resolved = 0").fetchone()[0]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def sql_time(moment: datetime) -> str:
    """A time in the same format SQLite's CURRENT_TIMESTAMP uses (UTC)."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def minutes_from_now(minutes: int) -> str:
    return sql_time(utc_now() + timedelta(minutes=minutes))
