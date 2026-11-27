"""User accounts: sign up, log in, and safe password storage.

Passwords are never saved as plain text. We save a "hash": a scrambled
fingerprint of the password that cannot be turned back into the password.
To check a login, we scramble what was typed the same way and compare.
"""

import hashlib
import hmac
import os
import re
import sqlite3

from core.database import connect, create_tables

ADMIN = "admin"
EMPLOYEE = "employee"

# How many times the password is scrambled. More = slower for attackers to guess.
HASH_ITERATIONS = 600_000
MIN_PASSWORD_LENGTH = 8
USERNAME_RULE = re.compile(r"^[a-z0-9._-]{3,30}$")


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


# ---------- Accounts ----------
def count_users() -> int:
    create_tables()
    with connect() as db:
        return db.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def _public(row) -> dict:
    """The user details the app is allowed to see (never the password hash)."""
    return {
        "id": row["id"],
        "username": row["username"],
        "full_name": row["full_name"],
        "role": row["role"],
    }


def sign_up(full_name: str, username: str, password: str) -> tuple[dict | None, str | None]:
    """Create an account. Returns (user, None) on success or (None, error message).

    The very first account becomes the admin; everyone after that is an employee."""
    full_name = full_name.strip()
    username = username.strip().lower()

    if not full_name:
        return None, "Please enter your name."
    if not USERNAME_RULE.match(username):
        return None, "Username must be 3-30 characters: letters, numbers, dot, dash or underscore."
    if len(password) < MIN_PASSWORD_LENGTH:
        return None, f"Password must be at least {MIN_PASSWORD_LENGTH} characters."

    create_tables()
    with connect() as db:
        is_first_user = db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        role = ADMIN if is_first_user else EMPLOYEE
        try:
            cursor = db.execute(
                "INSERT INTO users (username, full_name, password_hash, role) VALUES (?, ?, ?, ?)",
                (username, full_name, hash_password(password), role),
            )
        except sqlite3.IntegrityError:  # the UNIQUE rule on username
            return None, "That username is already taken."
        row = db.execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return _public(row), None


def log_in(username: str, password: str) -> dict | None:
    """Return the user if the username and password are right, otherwise None."""
    create_tables()
    with connect() as db:
        row = db.execute(
            "SELECT * FROM users WHERE username = ?", (username.strip().lower(),)
        ).fetchone()

    if row is None:
        verify_password(password, _DUMMY_HASH)  # same wait as a real check
        return None
    if not verify_password(password, row["password_hash"]):
        return None
    return _public(row)
