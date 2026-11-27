"""User accounts: sign up, sign in, strong passwords, lockout and user management.

Passwords are never saved as plain text. We save a "hash": a scrambled
fingerprint of the password that cannot be turned back into the password.
To check a sign-in, we scramble what was typed the same way and compare.
"""

import hashlib
import hmac
import os
import re
import sqlite3
from datetime import datetime, timezone

from core.config import (
    DEPARTMENTS,
    FAILED_LOGIN_ALERT,
    LOCKOUT_ATTEMPTS,
    LOCKOUT_MINUTES,
    PASSWORD_MIN_LENGTH,
)
from core.database import connect, create_tables

ADMIN = "admin"
EMPLOYEE = "employee"

# How many times the password is scrambled. More = slower for attackers to guess.
HASH_ITERATIONS = 600_000
MIN_PASSWORD_LENGTH = PASSWORD_MIN_LENGTH
USERNAME_RULE = re.compile(r"^[a-z0-9._-]{3,30}$")
EMAIL_RULE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------- Passwords ----------
def hash_password(password: str) -> str:
    """Turn a password into a hash like  pbkdf2_sha256$600000$<salt>$<hash>.

    The "salt" is random bytes added before scrambling, so two people with the
    same password still get different hashes."""
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, HASH_ITERATIONS)
    return f"pbkdf2_sha256${HASH_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """True if `password` matches the saved hash."""
    try:
        _, iterations, salt_hex, hash_hex = stored_hash.split("$")
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
    except (ValueError, TypeError):
        return False
    # compare_digest takes the same time whether the first or last letter differs,
    # so attackers can't learn anything from how fast it answers
    return hmac.compare_digest(digest.hex(), hash_hex)


# A hash of nothing in particular, used so a wrong username takes as long as a wrong password
_DUMMY_HASH = hash_password("not-a-real-password")

COMMON_PASSWORDS = {"password", "password123", "password1!", "qwerty123!", "letmein123",
                    "welcome123", "welcome@123", "admin12345", "admin@1234", "1234567890",
                    "iloveyou12", "officemind1", "p@ssw0rd123"}

PASSWORD_RULES = (f"At least {PASSWORD_MIN_LENGTH} characters, with a letter, a number and a "
                  "symbol (like ! @ # - _). It can't contain your username.")


def password_problem(password: str, username: str = "") -> str | None:
    """Why a password isn't strong enough, or None if it's fine."""
    if len(password) < PASSWORD_MIN_LENGTH:
        return f"Password must be at least {PASSWORD_MIN_LENGTH} characters."
    if not re.search(r"[A-Za-z]", password):
        return "Password must include at least one letter."
    if not re.search(r"\d", password):
        return "Password must include at least one number."
    if not re.search(r"[^A-Za-z0-9]", password):
        return "Password must include at least one symbol, like ! @ # - or _."
    if username and len(username) >= 3 and username.lower() in password.lower():
        return "Password mustn't contain your username."
    if password.lower() in COMMON_PASSWORDS:
        return "That password is too common. Please choose another."
    return None


# ---------- Accounts ----------
def count_users() -> int:
    create_tables()
    with connect() as db:
        return db.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def _public(row) -> dict:
    """The user details the app is allowed to see (never the password hash)."""
    from modules.security.crypto import decrypt
    return {
        "id": row["id"],
        "username": row["username"],
        "full_name": row["full_name"],
        "role": row["role"],
        "department": row["department"],
        "clearance": int(row["clearance"]),
        "email": decrypt(row["email"]),
    }


def sign_up(full_name: str, username: str, password: str, department: str = "General",
            email: str | None = None) -> tuple[dict | None, str | None]:
    """Create an account. Returns (user, None) on success or (None, error message).

    The very first account becomes the admin; everyone after that is an employee.
    The email address is stored encrypted."""
    from modules.security.activity import log_activity
    from modules.security.crypto import encrypt

    full_name = full_name.strip()
    username = username.strip().lower()
    email = (email or "").strip() or None

    if not full_name:
        return None, "Please enter your name."
    if not USERNAME_RULE.match(username):
        return None, "Username must be 3-30 characters: letters, numbers, dot, dash or underscore."
    if email is not None and not EMAIL_RULE.match(email):
        return None, "Please enter a valid email address."
    if department not in DEPARTMENTS:
        return None, "Please choose a department."
    problem = password_problem(password, username)
    if problem:
        return None, problem

    create_tables()
    with connect() as db:
        is_first_user = db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        role = ADMIN if is_first_user else EMPLOYEE
        try:
            cursor = db.execute(
                """INSERT INTO users (username, full_name, password_hash, role, department, email)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (username, full_name, hash_password(password), role, department, encrypt(email)),
            )
        except sqlite3.IntegrityError:  # the UNIQUE rule on username
            return None, "That username is already taken."
        row = db.execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone()
    user = _public(row)
    log_activity(user, "signup", f"{role}, {department}")
    return user, None


# ---------- Signing in (with lockout) ----------
def _parse(timestamp: str) -> datetime:
    return datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def _failed_login_alert(username: str) -> None:
    from modules.security.activity import count_recent, raise_alert
    failures = count_recent("login_failed", 15, username)
    if failures >= FAILED_LOGIN_ALERT:
        raise_alert("failed_logins", username,
                    f"{failures} failed sign-ins for “{username}” in the last 15 minutes.")


def attempt_login(username: str, password: str) -> tuple[dict | None, str | None]:
    """Check a username and password. Returns (user, None) or (None, message).

    After LOCKOUT_ATTEMPTS wrong passwords in a row, the account is locked for
    LOCKOUT_MINUTES. Every attempt is written to the activity log, and the admin
    gets an alert when one username fails several times."""
    from modules.security.activity import log_activity, minutes_from_now, raise_alert, sql_time, utc_now

    username = username.strip().lower()
    create_tables()
    with connect() as db:
        row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

    wrong = "That username and password don't match. Check them and try again."
    if row is None:
        verify_password(password, _DUMMY_HASH)  # same wait as a real check
        log_activity(None, "login_failed", "unknown username", "warning", username=username)
        _failed_login_alert(username)
        return None, wrong

    if row["locked_until"] and row["locked_until"] > sql_time(utc_now()):
        verify_password(password, _DUMMY_HASH)
        log_activity(None, "login_failed", "account is locked", "warning", username=username)
        minutes = max(1, round((_parse(row["locked_until"]) - utc_now()).total_seconds() / 60))
        return None, (f"This account is locked after too many wrong passwords. Try again in {minutes} "
                      f"minute{'s' if minutes != 1 else ''}, or ask an admin to unlock it.")

    if not verify_password(password, row["password_hash"]):
        attempts = (row["failed_attempts"] or 0) + 1
        with connect() as db:
            if attempts >= LOCKOUT_ATTEMPTS:
                db.execute("UPDATE users SET failed_attempts = 0, locked_until = ? WHERE id = ?",
                           (minutes_from_now(LOCKOUT_MINUTES), row["id"]))
            else:
                db.execute("UPDATE users SET failed_attempts = ? WHERE id = ?", (attempts, row["id"]))
        log_activity(None, "login_failed", f"wrong password ({attempts}/{LOCKOUT_ATTEMPTS})", "warning",
                     username=username)
        if attempts >= LOCKOUT_ATTEMPTS:
            log_activity(None, "account_locked", f"for {LOCKOUT_MINUTES} minutes", "critical", username=username)
            raise_alert("account_locked", username,
                        f"{row['full_name']}'s account was locked after {LOCKOUT_ATTEMPTS} wrong passwords.",
                        level="critical")
            return None, f"Too many wrong passwords. This account is locked for {LOCKOUT_MINUTES} minutes."
        _failed_login_alert(username)
        left = LOCKOUT_ATTEMPTS - attempts
        if left <= 2:
            wrong += f" {left} attempt{'s' if left != 1 else ''} left before the account is locked."
        return None, wrong

    with connect() as db:
        db.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE id = ?", (row["id"],))
    user = _public(row)
    log_activity(user, "login")
    return user, None


def log_in(username: str, password: str) -> dict | None:
    """Return the user if the username and password are right, otherwise None."""
    return attempt_login(username, password)[0]


def change_password(user: dict, old_password: str, new_password: str) -> str | None:
    """Returns an error message, or None if the password was changed."""
    from modules.security.activity import log_activity
    with connect() as db:
        row = db.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
    if row is None or not verify_password(old_password, row["password_hash"]):
        return "Your current password isn't right."
    problem = password_problem(new_password, user["username"])
    if problem:
        return problem
    with connect() as db:
        db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(new_password), user["id"]))
    log_activity(user, "user_change", "changed own password")
    return None


# ---------- Admin: managing users ----------
def list_users() -> list[dict]:
    create_tables()
    with connect() as db:
        rows = db.execute("SELECT * FROM users ORDER BY role, full_name").fetchall()
    users = []
    for row in rows:
        user = _public(row)
        user["locked_until"] = row["locked_until"]
        user["created_at"] = row["created_at"]
        users.append(user)
    return users


def update_user(admin: dict, user_id: int, department: str, clearance: bool, email: str | None) -> str | None:
    """Admins change someone's department, confidential access and email."""
    from modules.security.activity import log_activity
    from modules.security.crypto import encrypt
    if admin["role"] != ADMIN:
        raise PermissionError("Only admins can change users.")
    if department not in DEPARTMENTS:
        return "Please choose a department."
    email = (email or "").strip() or None
    if email and not EMAIL_RULE.match(email):
        return "Please enter a valid email address."
    with connect() as db:
        row = db.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
        db.execute("UPDATE users SET department = ?, clearance = ?, email = ? WHERE id = ?",
                   (department, int(clearance), encrypt(email), user_id))
    log_activity(admin, "user_change",
                 f"{row['username']}: {department}, confidential access {'on' if clearance else 'off'}")
    return None


def unlock_user(admin: dict, user_id: int) -> None:
    from modules.security.activity import log_activity
    if admin["role"] != ADMIN:
        raise PermissionError("Only admins can unlock accounts.")
    with connect() as db:
        row = db.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
        db.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE id = ?", (user_id,))
    log_activity(admin, "user_change", f"unlocked {row['username']}")


def refresh_user(user: dict) -> dict:
    """Read the user again (an admin may have changed their department or access)."""
    create_tables()
    with connect() as db:
        row = db.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    return _public(row) if row else user
