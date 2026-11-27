"""Team Chat: channels, direct messages, files, pins, search, and Jitsi voice/video calls."""

import html

import streamlit as st

from core.config import CHAT_MAX_FILE_MB, CHAT_REFRESH_SECONDS, JITSI_DOMAIN
from core.ui import empty_state, icon, page_setup
from modules.chat.calls import KINDS, active_call, call_url, end_call, start_call
from modules.chat.store import (
    CHANNEL,
    DM,
    all_channels,
    channel_label,
    create_channel,
    everyone,
    list_messages,
    mark_read,
    member_ids,
    my_channels,
    online_ids,
    open_dm,
    pinned_messages,
    read_file,
    search_messages,
    send_file,
    send_message,
    set_members,
    toggle_pin,
    touch_presence,
)
from modules.helpdesk.tickets import friendly_time
from modules.security.activity import log_activity

user = page_setup("pages/7_Team_Chat.py", "Team Chat", "forum",
                  "Channels, direct messages and calls with your team.")
admin = user["role"] == "admin"
state = st.session_state

if "chat_message" in state:
    st.success(state.pop("chat_message"), icon=":material/check_circle:")

channels = my_channels(user)
if not channels:
    empty_state("forum", "No chats yet", "You'll see #general here as soon as your account is set up.")
    st.stop()
by_id = {c["id"]: c for c in channels}
if state.get("chat_channel") not in by_id:
    state.chat_channel = channels[0]["id"]
people = {p["id"]: p for p in everyone()}
online = online_ids()


def open_chat(channel_id: int) -> None:
    state.chat_channel = channel_id
    state.pop("reply_to", None)
    state.pop("joined_call", None)


list_column, chat_column = st.columns([1, 3], gap="medium")

# =====================================================================
# Left: channels and direct messages
# =====================================================================
with list_column, st.container(key="panel_chatlist"):
    st.markdown('<div class="om-section">Channels</div>', unsafe_allow_html=True)
    for c in [c for c in channels if c["kind"] == CHANNEL]:
        label = f"#{c['name']}" + (f"  ({c['unread']})" if c["unread"] else "")
        st.button(label, key=f"chan_{c['id']}", width="stretch", on_click=open_chat, args=(c["id"],),
                  type="primary" if c["id"] == state.chat_channel else "tertiary")

    st.markdown('<div class="om-section">Direct messages</div>', unsafe_allow_html=True)
    for c in [c for c in channels if c["kind"] == DM]:
        is_online = c["other_id"] in online
        label = c["display"] + (f"  ({c['unread']})" if c["unread"] else "")
        st.button(label, key=f"chan_{c['id']}", width="stretch", on_click=open_chat, args=(c["id"],),
                  icon=":material/radio_button_checked:" if is_online else ":material/radio_button_unchecked:",
                  help="Online" if is_online else "Offline",
                  type="primary" if c["id"] == state.chat_channel else "tertiary")

    with st.popover("New message", icon=":material/edit_square:", width="stretch"):
        others = [p for p in people.values() if p["id"] != user["id"]]
        if others:
            person = st.selectbox("Person", others, key="dm_person",
                                  format_func=lambda p: f"{p['full_name']} · {'online' if p['id'] in online else 'offline'}")
            if st.button("Open chat", type="primary", key="dm_open"):
                open_chat(open_dm(user, person["id"]))
                st.rerun()
        else:
            st.caption("Nobody else has an account yet.")

    # Admins: create channels and choose members
    if admin:
        with st.expander("Manage channels", icon=":material/settings:"):
            with st.form("new_channel", clear_on_submit=True, border=False):
                name = st.text_input("New channel", placeholder="e.g. it")
                topic = st.text_input("Topic", placeholder="e.g. IT questions and outages")
                members = st.multiselect("Members", list(people), format_func=lambda i: people[i]["full_name"])
                if st.form_submit_button("Create channel", type="primary", icon=":material/add:"):
                    new_id, error = create_channel(user, name, topic, members)
                    if error:
                        st.error(error, icon=":material/error:")
                    else:
                        open_chat(new_id)
                        state.chat_message = f"Channel #{name.strip().lstrip('#').lower()} created."
                        st.rerun()
            st.divider()
            manageable = all_channels()
            target = st.selectbox("Edit members of", manageable, format_func=lambda c: f"#{c['name']}",
                                  key="manage_target")
            current = member_ids(target["id"])
            chosen = st.multiselect("Members", list(people), default=[i for i in current if i in people],
                                    format_func=lambda i: people[i]["full_name"], key=f"members_{target['id']}")
            if st.button("Save members", key="save_members", icon=":material/save:"):
                set_members(user, target["id"], chosen)
                state.chat_message = f"Members of #{target['name']} updated."
                st.rerun()

# =====================================================================
# Right: the open conversation
# =====================================================================
channel = by_id[state.chat_channel]
channel_id = channel["id"]


def message_html(m: dict) -> str:
    """One chat bubble (escaped, so messages can't inject HTML)."""
    if m["kind"] in ("system", "call"):
        symbol = icon("call" if m["kind"] == "call" else "info", 16)
        return (f'<div class="om-msg-system">{symbol} {html.escape(m["body"])} · '
                f'{friendly_time(m["created_at"])}</div>')
    mine = m["user_id"] == user["id"]
    reply = ""
    if m.get("reply_preview"):
        reply = (f'<div class="om-msg-reply">{icon("reply", 14)} <strong>{html.escape(m["reply_preview"]["author"])}</strong>: '
                 f'{html.escape(m["reply_preview"]["text"][:120])}</div>')
    ticks = ""
    if mine:
        ticks = (f'<span class="om-ticks om-ticks-read" title="Read by everyone">{icon("done_all", 15)}</span>'
                 if m["read_by_all"] else
                 f'<span class="om-ticks" title="Sent">{icon("done_all" if m["read_by_some"] else "done", 15)}</span>')
    pin = f'<span class="om-msg-pin">{icon("push_pin", 14)}</span>' if m["pinned"] else ""
    body = f'<div class="om-msg-body">{html.escape(m["body"])}</div>' if m["body"] else ""
    return (f'<div class="om-msg {"om-msg-mine" if mine else "om-msg-theirs"}">'
            f'<div class="om-msg-head"><strong>{html.escape("You" if mine else m["author"])}</strong>'
            f'<span>{friendly_time(m["created_at"])}</span>{pin}{ticks}</div>{reply}{body}</div>')


def reply_to(message_id: int) -> None:
    state.reply_to = message_id


@st.fragment(run_every=CHAT_REFRESH_SECONDS)
def conversation() -> None:
    """Re-runs every few seconds on its own, so new messages appear without reloading."""
    touch_presence(user)
    messages = list_messages(user, channel_id)
    mark_read(user, channel_id)
    with st.container(height=480, key="panel_messages", autoscroll=True):
        if not messages:
            empty_state("chat", "No messages yet", "Say hello! Messages are encrypted when stored.")
        for m in messages:
            with st.container(key=f"msg_{m['id']}"):
                st.markdown(message_html(m), unsafe_allow_html=True)
                if m["kind"] == "image":
                    try:
                        st.image(read_file(user, m["id"])[1], caption=m["file_name"], width=320)
                    except Exception:
                        st.caption("Image not available.")
                if m["kind"] in ("image", "file"):
                    def download(message_id=m["id"]) -> bytes:
                        log_activity(user, "chat_download", "a chat file")
                        return read_file(user, message_id)[1]
                    st.download_button(f"{m['file_name']} ({max(1, (m['file_size'] or 0) // 1024)} KB)",
                                       data=download, file_name=m["file_name"], on_click="ignore",
                                       icon=":material/attach_file:", key=f"file_{m['id']}", type="tertiary")
                if m["kind"] not in ("system", "call"):
                    with st.popover("", icon=":material/more_horiz:", key=f"menu_{m['id']}", help="Reply or pin"):
                        st.button("Reply", key=f"reply_{m['id']}", icon=":material/reply:",
                                  on_click=reply_to, args=(m["id"],))
                        if st.button("Unpin" if m["pinned"] else "Pin", key=f"pin_{m['id']}",
                                     icon=":material/push_pin:"):
                            toggle_pin(user, m["id"])
                            st.rerun(scope="fragment")


with chat_column:
    # ---------- Header: name, members, call buttons, pinned, search ----------
    if channel["kind"] == DM:
        status = "online" if channel["other_id"] in online else "offline"
        subtitle = f"Direct message · {status}"
    else:
        here = len([i for i in member_ids(channel_id) if i in online])
        subtitle = (html.escape(channel["topic"]) + " · " if channel["topic"] else "") + \
            f"{channel['members']} members · {here} online"
    title_col, voice_col, video_col, pin_col, search_col = st.columns([4, 1, 1, 1, 1], vertical_alignment="center")
    title_col.markdown(f'<div class="om-chat-title">{html.escape(channel_label(channel))}</div>'
                       f'<div class="om-muted">{subtitle}</div>', unsafe_allow_html=True)
    call = active_call(channel_id)
    for column, kind, symbol in ((voice_col, "voice", "call"), (video_col, "video", "videocam")):
        if column.button("", icon=f":material/{symbol}:", key=f"start_{kind}", help=f"Start a {KINDS[kind].lower()}",
                         disabled=bool(call)):
            state.joined_call = start_call(user, channel_id, kind)["id"]
            st.rerun()
    with pin_col.popover("", icon=":material/push_pin:", help="Pinned messages"):
        pins = pinned_messages(user, channel_id)
        if not pins:
            st.caption("No pinned messages. Use ⋯ on a message to pin it.")
        for m in pins:
            st.markdown(f"**{html.escape(m['author'])}**: {html.escape(m['body'] or m['file_name'] or '')}")
    with search_col.popover("", icon=":material/search:", help="Search messages"):
        query = st.text_input("Search all your chats", key="chat_search", placeholder="e.g. vpn password")
        if query:
            found = search_messages(user, query)
            if not found:
                st.caption("No messages found.")
            for m in found[:20]:
                st.markdown(f"**{html.escape(m['chat'])}** · {html.escape(m['author'])} · {friendly_time(m['created_at'])}  \n"
                            f"{html.escape((m['body'] or m['file_name'] or '')[:160])}")
                st.button("Open chat", key=f"goto_{m['id']}", on_click=open_chat, args=(m["channel_id"],))

    # ---------- A call in progress ----------
    if call:
        with st.container(key="panel_call"):
            starter = people.get(call["started_by"], {}).get("full_name", "Someone")
            info, join, window, stop = st.columns([3, 1, 1.2, 1], vertical_alignment="center")
            info.markdown(f'<div class="om-call-live">{icon("radio_button_checked", 16)} {KINDS[call["kind"]]} in progress'
                          f'</div><div class="om-muted">Started by {html.escape(starter)} · private room</div>',
                          unsafe_allow_html=True)
            joined = state.get("joined_call") == call["id"]
            if join.button("Leave" if joined else "Join here", key="join_call", type="secondary" if joined else "primary",
                           icon=":material/logout:" if joined else ":material/login:"):
                state.joined_call = None if joined else call["id"]
                st.rerun()
            window.link_button("New window", call_url(call, user), icon=":material/open_in_new:",
                               help="Use this for screen sharing")
            if stop.button("End call", key="end_call", icon=":material/call_end:"):
                state.chat_message = f"Call ended ({end_call(user, call['id'])})."
                state.joined_call = None
                st.rerun()
            if joined:
                st.iframe(call_url(call, user), height=520)
                st.caption(f"Calls run on {JITSI_DOMAIN}. Use Jitsi's buttons to mute, turn the camera off or "
                           "hang up. Screen sharing works in “New window”.")

    # ---------- Messages ----------
    conversation()

    # ---------- Replying to… ----------
    if state.get("reply_to"):
        original = next((m for m in list_messages(user, channel_id) if m["id"] == state.reply_to), None)
        if original:
            text_col, cancel_col = st.columns([6, 1], vertical_alignment="center")
            text_col.markdown(f'<div class="om-msg-reply">{icon("reply", 14)} Replying to '
                              f'<strong>{html.escape(original["author"])}</strong>: '
                              f'{html.escape((original["body"] or original["file_name"] or "")[:120])}</div>',
                              unsafe_allow_html=True)
            if cancel_col.button("", icon=":material/close:", key="cancel_reply", help="Cancel reply"):
                state.pop("reply_to", None)
                st.rerun()

# ---------- Write a message (text, images or files) ----------
sent = st.chat_input(f"Message {channel_label(channel)}", accept_file="multiple",
                     max_upload_size=CHAT_MAX_FILE_MB, key="chat_box")
if sent:
    reply = state.pop("reply_to", None)
    errors = []
    files = list(sent.files or [])
    if files:
        for i, f in enumerate(files):
            error = send_file(user, channel_id, f.name, f.getvalue(), caption=sent.text if i == 0 else "",
                              reply_to=reply)
            if error:
                errors.append(f"{f.name}: {error}")
    elif sent.text:
        error = send_message(user, channel_id, sent.text, reply_to=reply)
        if error:
            errors.append(error)
    for error in errors:
        st.error(error, icon=":material/error:")
    if not errors:
        st.rerun()
