"""Voice and video calls with Jitsi Meet (free and open-source).

Each call gets its own random, unguessable room name (about 128 random bits), so
people outside the chat can't find it. Starting and ending a call posts a message
in the chat and is recorded in the Activity Log.

Limits to know about:
- The call itself runs on the Jitsi server in JITSI_DOMAIN (meet.jit.si by default),
  not inside OfficeMind. For calls that never leave the company, run your own
  Jitsi server and set OFFICEMIND_JITSI to its address.
- meet.jit.si may ask the first person in a room to sign in, and limits calls that
  are embedded in other websites; "Open in new window" always works.
- Screen sharing is blocked by the browser inside an embedded frame, so it needs
  "Open in new window".
"""

import html
import json
import secrets
from datetime import datetime, timezone
from urllib.parse import quote

from core.config import JITSI_DOMAIN
from core.database import connect
from modules.chat.store import _channel_name, _require_member, _system, create_chat_tables
from modules.security.activity import log_activity

KINDS = {"voice": "Voice call", "video": "Video call"}


def new_room_name() -> str:
    """A private room name nobody can guess: OfficeMind + 22 random letters/numbers."""
    return "OfficeMind" + "".join(secrets.choice("abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789")
                                  for _ in range(22))


def active_call(channel_id: int) -> dict | None:
    """The call that's running in this chat right now (calls over 4 hours old count as ended)."""
    create_chat_tables()
    with connect() as db:
        row = db.execute("""SELECT * FROM chat_calls WHERE channel_id = ? AND ended_at IS NULL
                            AND started_at >= datetime('now', '-4 hours') ORDER BY id DESC LIMIT 1""",
                         (channel_id,)).fetchone()
    return dict(row) if row else None


def start_call(user: dict, channel_id: int, kind: str) -> dict:
    """Start a call (or return the one already running in this chat)."""
    _require_member(user, channel_id)
    if kind not in KINDS:
        raise ValueError("Unknown call type.")
    running = active_call(channel_id)
    if running:
        return running
    room = new_room_name()
    with connect() as db:
        db.execute("INSERT INTO chat_calls (channel_id, room, kind, started_by) VALUES (?, ?, ?, ?)",
                   (channel_id, room, kind, user["id"]))
    _system(channel_id, f"{KINDS[kind]} started by {user['full_name']}", kind="call")
    log_activity(user, "call_start", f"{KINDS[kind]} in {_channel_name(channel_id)}")
    return active_call(channel_id)


def end_call(user: dict, call_id: int) -> str:
    """End a call for everyone. Returns how long it lasted, e.g. '12 min'."""
    with connect() as db:
        call = db.execute("SELECT * FROM chat_calls WHERE id = ?", (call_id,)).fetchone()
    if call is None:
        raise ValueError("No such call.")
    _require_member(user, call["channel_id"])
    if call["ended_at"]:
        return "already ended"
    started = datetime.strptime(call["started_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    minutes = max(1, round((datetime.now(timezone.utc) - started).total_seconds() / 60))
    with connect() as db:
        db.execute("UPDATE chat_calls SET ended_at = CURRENT_TIMESTAMP, ended_by = ? WHERE id = ?", (user["id"], call_id))
    length = f"{minutes} min"
    _system(call["channel_id"], f"{KINDS[call['kind']]} ended by {user['full_name']} · {length}", kind="call")
    log_activity(user, "call_end", f"{KINDS[call['kind']]} in {_channel_name(call['channel_id'])}, {length}")
    return length


def call_url(call: dict, user: dict) -> str:
    """Link to the Jitsi room, with the person's name filled in and the right devices on."""
    config = {
        "userInfo.displayName": json.dumps(user["full_name"]),
        "config.prejoinPageEnabled": "false",
        "config.prejoinConfig.enabled": "false",  # newer Jitsi versions use this name
        "config.startWithVideoMuted": "true" if call["kind"] == "voice" else "false",
        "config.startAudioOnly": "true" if call["kind"] == "voice" else "false",
        "config.disableDeepLinking": "true",
    }
    fragment = "&".join(f"{k}={quote(v)}" for k, v in config.items())
    return f"https://{JITSI_DOMAIN}/{call['room']}#{fragment}"


def call_frame_html(call: dict, user: dict, height: int = 520) -> str:
    """The Jitsi room embedded in the page. Jitsi's own toolbar has mute, camera on/off and hang-up."""
    return (f'<iframe src="{html.escape(call_url(call, user))}" '
            f'allow="camera; microphone; fullscreen; display-capture; autoplay" '
            f'style="width:100%;height:{height}px;border:0;border-radius:12px;background:#111"></iframe>')
