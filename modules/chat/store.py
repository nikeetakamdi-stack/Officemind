"""Team Chat: channels, direct messages, messages, files, read status, pins and presence.

Everything is stored in the same SQLite database as the rest of OfficeMind.
Message text and file names are encrypted; attached files are encrypted on disk.
Only members of a chat can read or write in it.
"""

import re
import uuid
from pathlib import Path

from core.config import CHAT_FILES_DIR, CHAT_MAX_FILE_MB, ONLINE_SECONDS
from core.database import connect, create_tables
from modules.security.activity import log_activity
from modules.security.crypto import _get_fernet, decrypt, encrypt

CHANNEL, DM = "channel", "dm"
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
CHANNEL_NAME_RULE = re.compile(r"^[a-z0-9][a-z0-9-]{1,29}$")


def create_chat_tables() -> None:
    create_tables()
    with connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS chat_channels (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL UNIQUE,     -- "it" for #it, or "dm:3:7" for a direct chat
                kind       TEXT NOT NULL CHECK (kind IN ('channel', 'dm')),
                topic      TEXT NOT NULL DEFAULT '',
                created_by INTEGER REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
        db.execute("""
            CREATE TABLE IF NOT EXISTS chat_members (
                channel_id   INTEGER NOT NULL REFERENCES chat_channels(id),
                user_id      INTEGER NOT NULL REFERENCES users(id),
                last_read_id INTEGER NOT NULL DEFAULT 0,
                joined_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (channel_id, user_id)
            )""")
        db.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL REFERENCES chat_channels(id),
                user_id    INTEGER REFERENCES users(id),   -- NULL for system messages
                kind       TEXT NOT NULL DEFAULT 'text',   -- text, image, file, system, call
                body       TEXT,                           -- encrypted
                file_name  TEXT,                           -- encrypted
                file_path  TEXT,                           -- random name inside CHAT_FILES_DIR
                file_size  INTEGER,
                reply_to   INTEGER REFERENCES chat_messages(id),
                pinned     INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
        db.execute("CREATE INDEX IF NOT EXISTS chat_messages_channel ON chat_messages(channel_id, id)")
        db.execute("""
            CREATE TABLE IF NOT EXISTS user_presence (
                user_id   INTEGER PRIMARY KEY REFERENCES users(id),
                last_seen TEXT NOT NULL
            )""")
        db.execute("""
            CREATE TABLE IF NOT EXISTS chat_calls (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL REFERENCES chat_channels(id),
                room       TEXT NOT NULL UNIQUE,
                kind       TEXT NOT NULL CHECK (kind IN ('voice', 'video')),
                started_by INTEGER REFERENCES users(id),
                started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                ended_at   TEXT,
                ended_by   INTEGER REFERENCES users(id)
            )""")
        # Everyone is in #general
        if not db.execute("SELECT 1 FROM chat_channels WHERE name = 'general'").fetchone():
            db.execute("INSERT INTO chat_channels (name, kind, topic) VALUES ('general', 'channel', "
                       "'Company-wide announcements and chat')")
        general = db.execute("SELECT id FROM chat_channels WHERE name = 'general'").fetchone()["id"]
        db.execute("""INSERT OR IGNORE INTO chat_members (channel_id, user_id)
                      SELECT ?, id FROM users""", (general,))


def _require_admin(user: dict, what: str) -> None:
    if user["role"] != "admin":
        raise PermissionError(f"Only admins can {what}.")


def is_member(user: dict, channel_id: int) -> bool:
    with connect() as db:
        return bool(db.execute("SELECT 1 FROM chat_members WHERE channel_id = ? AND user_id = ?",
                               (channel_id, user["id"])).fetchone())


def _require_member(user: dict, channel_id: int) -> None:
    if not is_member(user, channel_id):
        raise PermissionError("You're not a member of this chat.")


def channel_label(channel: dict) -> str:
    return channel["display"] if channel["kind"] == DM else f"#{channel['name']}"


# ---------- Channels (admins) ----------
def create_channel(admin: dict, name: str, topic: str, member_ids: list[int]) -> tuple[int | None, str | None]:
    _require_admin(admin, "create channels")
    name = name.strip().lstrip("#").lower()
    if not CHANNEL_NAME_RULE.match(name):
        return None, "Channel names use 2-30 lowercase letters, numbers or dashes, e.g. it-support."
    create_chat_tables()
    with connect() as db:
        if db.execute("SELECT 1 FROM chat_channels WHERE name = ?", (name,)).fetchone():
            return None, f"#{name} already exists."
        cursor = db.execute("INSERT INTO chat_channels (name, kind, topic, created_by) VALUES (?, 'channel', ?, ?)",
                            (name, topic.strip()[:200], admin["id"]))
        channel_id = cursor.lastrowid
        for user_id in {admin["id"], *member_ids}:
            db.execute("INSERT OR IGNORE INTO chat_members (channel_id, user_id) VALUES (?, ?)", (channel_id, user_id))
    log_activity(admin, "channel_change", f"created #{name} with {len({admin['id'], *member_ids})} members")
    _system(channel_id, f"{admin['full_name']} created #{name}")
    return channel_id, None


def set_members(admin: dict, channel_id: int, member_ids: list[int]) -> None:
    """Make the channel's members exactly `member_ids` (the admin always stays)."""
    _require_admin(admin, "change channel members")
    with connect() as db:
        channel = db.execute("SELECT * FROM chat_channels WHERE id = ?", (channel_id,)).fetchone()
        if channel is None or channel["kind"] != CHANNEL:
            raise ValueError("Only channels have members to manage.")
        current = {r["user_id"] for r in db.execute("SELECT user_id FROM chat_members WHERE channel_id = ?", (channel_id,))}
        wanted = set(member_ids) | {admin["id"]}
        names = {r["id"]: r["full_name"] for r in db.execute("SELECT id, full_name FROM users")}
        for user_id in wanted - current:
            db.execute("INSERT INTO chat_members (channel_id, user_id) VALUES (?, ?)", (channel_id, user_id))
        for user_id in current - wanted:
            db.execute("DELETE FROM chat_members WHERE channel_id = ? AND user_id = ?", (channel_id, user_id))
    added, removed = wanted - current, current - wanted
    if added or removed:
        log_activity(admin, "channel_change", f"#{channel['name']}: +{len(added)} / -{len(removed)} members")
    for user_id in added:
        _system(channel_id, f"{names.get(user_id, 'Someone')} was added by {admin['full_name']}")
    for user_id in removed:
        _system(channel_id, f"{names.get(user_id, 'Someone')} was removed by {admin['full_name']}")


def all_channels() -> list[dict]:
    create_chat_tables()
    with connect() as db:
        return [dict(r) for r in db.execute("SELECT * FROM chat_channels WHERE kind = 'channel' ORDER BY name")]


def member_ids(channel_id: int) -> list[int]:
    with connect() as db:
        return [r["user_id"] for r in db.execute("SELECT user_id FROM chat_members WHERE channel_id = ?", (channel_id,))]


# ---------- Direct messages ----------
def open_dm(user: dict, other_id: int) -> int:
    """The direct chat between two people (created the first time)."""
    if other_id == user["id"]:
        raise ValueError("Pick someone else.")
    create_chat_tables()
    a, b = sorted((user["id"], other_id))
    name = f"dm:{a}:{b}"
    with connect() as db:
        if not db.execute("SELECT 1 FROM users WHERE id = ?", (other_id,)).fetchone():
            raise ValueError("Unknown person.")
        row = db.execute("SELECT id FROM chat_channels WHERE name = ?", (name,)).fetchone()
        if row:
            return row["id"]
        channel_id = db.execute("INSERT INTO chat_channels (name, kind, created_by) VALUES (?, 'dm', ?)",
                                (name, user["id"])).lastrowid
        db.execute("INSERT INTO chat_members (channel_id, user_id) VALUES (?, ?), (?, ?)", (channel_id, a, channel_id, b))
    return channel_id


# ---------- My chats, unread counts ----------
def my_channels(user: dict) -> list[dict]:
    """Every chat this person is in, with unread count. DMs get the other person's name."""
    create_chat_tables()
    with connect() as db:
        rows = db.execute("""
            SELECT c.*, m.last_read_id,
                   (SELECT COUNT(*) FROM chat_messages x WHERE x.channel_id = c.id AND x.id > m.last_read_id
                      AND COALESCE(x.user_id, -1) != ? AND x.kind != 'system') AS unread,
                   (SELECT MAX(id) FROM chat_messages x WHERE x.channel_id = c.id) AS last_id,
                   (SELECT COUNT(*) FROM chat_members y WHERE y.channel_id = c.id) AS members
            FROM chat_channels c JOIN chat_members m ON m.channel_id = c.id AND m.user_id = ?
        """, (user["id"], user["id"])).fetchall()
        names = {r["id"]: r for r in db.execute("SELECT id, full_name, username FROM users")}
    channels = []
    for row in rows:
        channel = dict(row)
        if channel["kind"] == DM:
            ids = [int(i) for i in channel["name"].split(":")[1:]]
            other = next((i for i in ids if i != user["id"]), user["id"])
            channel["other_id"] = other
            channel["display"] = names[other]["full_name"] if other in names else "Unknown"
        else:
            channel["display"] = f"#{channel['name']}"
        channels.append(channel)
    channels.sort(key=lambda c: (c["kind"] != CHANNEL, c["kind"] == CHANNEL and c["name"] != "general",
                                 c["display"].lower()))
    return channels


def unread_total(user: dict) -> int:
    try:
        return sum(c["unread"] for c in my_channels(user))
    except Exception:
        return 0


def mark_read(user: dict, channel_id: int) -> None:
    with connect() as db:
        db.execute("""UPDATE chat_members SET last_read_id =
                        COALESCE((SELECT MAX(id) FROM chat_messages WHERE channel_id = ?), 0)
                      WHERE channel_id = ? AND user_id = ?""", (channel_id, channel_id, user["id"]))


# ---------- Messages ----------
def _system(channel_id: int, text: str, kind: str = "system") -> int:
    with connect() as db:
        return db.execute("INSERT INTO chat_messages (channel_id, user_id, kind, body) VALUES (?, NULL, ?, ?)",
                          (channel_id, kind, encrypt(text))).lastrowid


def _channel_name(channel_id: int) -> str:
    with connect() as db:
        row = db.execute("SELECT name, kind FROM chat_channels WHERE id = ?", (channel_id,)).fetchone()
    return "a direct chat" if row and row["kind"] == DM else f"#{row['name']}" if row else "?"


def send_message(user: dict, channel_id: int, text: str, reply_to: int | None = None) -> str | None:
    """Returns an error message, or None if it was sent."""
    _require_member(user, channel_id)
    text = text.strip()
    if not text:
        return "The message is empty."
    if len(text) > 4000:
        return "Messages can be at most 4,000 characters."
    with connect() as db:
        if reply_to and not db.execute("SELECT 1 FROM chat_messages WHERE id = ? AND channel_id = ?",
                                       (reply_to, channel_id)).fetchone():
            reply_to = None
        db.execute("INSERT INTO chat_messages (channel_id, user_id, kind, body, reply_to) VALUES (?, ?, 'text', ?, ?)",
                   (channel_id, user["id"], encrypt(text), reply_to))
    mark_read(user, channel_id)
    log_activity(user, "chat_message", f"in {_channel_name(channel_id)}")  # not the text itself
    return None


def send_file(user: dict, channel_id: int, file_name: str, data: bytes, caption: str = "",
              reply_to: int | None = None) -> str | None:
    """Attach a file or image (encrypted on disk). Returns an error message, or None."""
    _require_member(user, channel_id)
    if len(data) > CHAT_MAX_FILE_MB * 1024 * 1024:
        return f"Files can be at most {CHAT_MAX_FILE_MB} MB."
    safe_name = Path(file_name).name[:120] or "file"
    kind = "image" if Path(safe_name).suffix.lower() in IMAGE_TYPES else "file"
    CHAT_FILES_DIR.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid.uuid4().hex}.bin"  # random name: nothing about the file is visible on disk
    (CHAT_FILES_DIR / stored).write_bytes(_get_fernet().encrypt(data))
    with connect() as db:
        db.execute("""INSERT INTO chat_messages (channel_id, user_id, kind, body, file_name, file_path, file_size, reply_to)
                      VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                   (channel_id, user["id"], kind, encrypt(caption.strip()) if caption.strip() else None,
                    encrypt(safe_name), stored, len(data), reply_to))
    mark_read(user, channel_id)
    log_activity(user, "chat_file", f"{kind} ({len(data) // 1024} KB) in {_channel_name(channel_id)}")
    return None


def read_file(user: dict, message_id: int) -> tuple[str, bytes]:
    """(file name, bytes) of an attachment, for members of that chat only."""
    with connect() as db:
        row = db.execute("SELECT * FROM chat_messages WHERE id = ?", (message_id,)).fetchone()
    if row is None or not row["file_path"]:
        raise ValueError("No such file.")
    _require_member(user, row["channel_id"])
    data = _get_fernet().decrypt((CHAT_FILES_DIR / Path(row["file_path"]).name).read_bytes())
    return decrypt(row["file_name"]), data


def _decrypt_message(row, names: dict) -> dict:
    message = dict(row)
    message["body"] = decrypt(message["body"]) or ""
    message["file_name"] = decrypt(message["file_name"])
    message["author"] = names.get(message["user_id"], "OfficeMind") if message["user_id"] else "OfficeMind"
    return message


def list_messages(user: dict, channel_id: int, limit: int = 100) -> list[dict]:
    """The latest messages, oldest first, with reply previews and read status."""
    _require_member(user, channel_id)
    with connect() as db:
        names = {r["id"]: r["full_name"] for r in db.execute("SELECT id, full_name FROM users")}
        rows = db.execute("SELECT * FROM (SELECT * FROM chat_messages WHERE channel_id = ? ORDER BY id DESC LIMIT ?) "
                          "ORDER BY id", (channel_id, limit)).fetchall()
        others_read = [r["last_read_id"] for r in db.execute(
            "SELECT last_read_id FROM chat_members WHERE channel_id = ? AND user_id != ?", (channel_id, user["id"]))]
        reply_ids = {r["reply_to"] for r in rows if r["reply_to"]}
        replies = {r["id"]: r for r in db.execute(
            f"SELECT * FROM chat_messages WHERE id IN ({','.join('?' * len(reply_ids))})", tuple(reply_ids))} if reply_ids else {}
    messages = []
    for row in rows:
        message = _decrypt_message(row, names)
        # Read ticks: ✓ sent, ✓✓ read by everyone else in the chat
        message["read_by_all"] = bool(others_read) and min(others_read) >= message["id"]
        message["read_by_some"] = any(r >= message["id"] for r in others_read)
        if message["reply_to"] in replies:
            original = _decrypt_message(replies[message["reply_to"]], names)
            message["reply_preview"] = {"author": original["author"],
                                        "text": original["body"] or original["file_name"] or ""}
        messages.append(message)
    return messages


def toggle_pin(user: dict, message_id: int) -> bool:
    """Pin or unpin a message (any member). Returns the new pinned state."""
    with connect() as db:
        row = db.execute("SELECT channel_id, pinned FROM chat_messages WHERE id = ?", (message_id,)).fetchone()
    if row is None:
        raise ValueError("No such message.")
    _require_member(user, row["channel_id"])
    pinned = not row["pinned"]
    with connect() as db:
        db.execute("UPDATE chat_messages SET pinned = ? WHERE id = ?", (int(pinned), message_id))
    log_activity(user, "chat_pin", f"{'pinned' if pinned else 'unpinned'} a message in {_channel_name(row['channel_id'])}")
    return pinned


def pinned_messages(user: dict, channel_id: int) -> list[dict]:
    return [m for m in list_messages(user, channel_id, limit=1000) if m["pinned"]]


def search_messages(user: dict, query: str, limit: int = 50) -> list[dict]:
    """Messages containing every word of `query`, in chats this person belongs to (newest first).
    Messages are encrypted, so they're decrypted and searched here, not in SQL."""
    words = query.lower().split()
    if not words:
        return []
    chats = {c["id"]: c for c in my_channels(user)}
    if not chats:
        return []
    with connect() as db:
        names = {r["id"]: r["full_name"] for r in db.execute("SELECT id, full_name FROM users")}
        rows = db.execute(f"SELECT * FROM chat_messages WHERE channel_id IN ({','.join('?' * len(chats))}) "
                          "AND kind != 'system' ORDER BY id DESC LIMIT 5000", tuple(chats)).fetchall()
    found = []
    for row in rows:
        message = _decrypt_message(row, names)
        text = f"{message['body']} {message['file_name'] or ''}".lower()
        if all(w in text for w in words):
            message["chat"] = channel_label(chats[message["channel_id"]])
            found.append(message)
            if len(found) >= limit:
                break
    return found


# ---------- Presence ----------
def touch_presence(user: dict) -> None:
    try:
        create_chat_tables()
        with connect() as db:
            db.execute("INSERT INTO user_presence (user_id, last_seen) VALUES (?, CURRENT_TIMESTAMP) "
                       "ON CONFLICT(user_id) DO UPDATE SET last_seen = CURRENT_TIMESTAMP", (user["id"],))
    except Exception:
        pass


def online_ids() -> set[int]:
    with connect() as db:
        return {r["user_id"] for r in db.execute(
            "SELECT user_id FROM user_presence WHERE last_seen >= datetime('now', ?)", (f"-{ONLINE_SECONDS} seconds",))}


def everyone() -> list[dict]:
    create_tables()
    with connect() as db:
        return [dict(r) for r in db.execute("SELECT id, full_name, username, department FROM users ORDER BY full_name")]
