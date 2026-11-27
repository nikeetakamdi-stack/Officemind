"""Helpdesk page.

Employees: raise a ticket and follow their own tickets.
Admins: see every ticket, change its status and reply.
"""

import html

import streamlit as st

from core.config import TICKET_CATEGORIES
from core.ui import apply_style, is_admin, require_login, sidebar_menu, status_badge
from modules.helpdesk.tickets import (
    STATUSES,
    add_reply,
    create_ticket,
    friendly_time,
    list_replies,
    list_tickets,
    update_status,
)

st.set_page_config(page_title="Helpdesk · OfficeMind", page_icon="🎧")
apply_style()
user = require_login()  # not logged in? -> login page
sidebar_menu()
admin = is_admin()

subtitle = (
    "Every ticket from your team. Update the status and reply to keep people informed."
    if admin
    else "Having a problem? Raise a ticket and follow its progress here."
)
st.markdown(
    f"""
    <div class="om-page-title">🎧 <span class="om-gradient">Helpdesk</span></div>
    <p class="om-page-subtitle">{subtitle}</p>
    """,
    unsafe_allow_html=True,
)

# A message saved before the page refreshed (e.g. "Ticket #4 created")
if "helpdesk_message" in st.session_state:
    st.success(st.session_state.pop("helpdesk_message"), icon=":material/check_circle:")


# ---------- Building blocks ----------
def ticket_header(ticket: dict) -> None:
    """Top of a ticket card: number, title, status badge and small details."""
    by = f" · by {html.escape(ticket['author'])}" if admin else ""
    replies = ticket["reply_count"]
    reply_text = f" · 💬 {replies} repl{'y' if replies == 1 else 'ies'}" if replies else ""
    st.markdown(
        f"""
        <div class="om-ticket-top">
          <span class="om-ticket-title">
            <span class="om-ticket-id">#{ticket['id']}</span> {html.escape(ticket['title'])}
          </span>
          {status_badge(ticket['status'], STATUSES[ticket['status']])}
        </div>
        <div class="om-ticket-meta">
          {html.escape(ticket['category'])}{by} · {friendly_time(ticket['created_at'])}{reply_text}
        </div>
        """,
        unsafe_allow_html=True,
    )


def ticket_conversation(ticket: dict) -> None:
    """The problem description followed by every reply."""
    st.markdown(
        f'<div class="om-ticket-desc">{html.escape(ticket["description"])}</div>',
        unsafe_allow_html=True,
    )
    for reply in list_replies(ticket["id"]):
        st.markdown(
            f"""
            <div class="om-reply">
              <div class="om-reply-head">
                <strong>{html.escape(reply['author'])}</strong>
                <span class="om-role om-role-{reply['author_role']}">{reply['author_role'].title()}</span>
                <span class="om-reply-time">{friendly_time(reply['created_at'])}</span>
              </div>
              <div class="om-reply-body">{html.escape(reply['message'])}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def admin_controls(ticket: dict) -> None:
    """Change the status and/or add a reply, then press Save."""
    status_keys = list(STATUSES)
    with st.form(f"manage_{ticket['id']}", clear_on_submit=True):
        new_status = st.selectbox(
            "Status",
            status_keys,
            index=status_keys.index(ticket["status"]),
            format_func=lambda key: STATUSES[key],
        )
        reply = st.text_area(
            "Reply or note (optional)",
            placeholder="e.g. We've reset your VPN access. Please try again.",
            height=90,
        )
        saved = st.form_submit_button("Save", type="primary", icon=":material/save:")

    if saved:
        changes = []
        if new_status != ticket["status"]:
            update_status(user, ticket["id"], new_status)
            changes.append(f"status → {STATUSES[new_status]}")
        if reply.strip():
            error = add_reply(user, ticket["id"], reply)
            if error:
                st.error(error)
                return
            changes.append("reply added")
        if changes:
            st.session_state.helpdesk_message = f"Ticket #{ticket['id']}: " + ", ".join(changes)
            st.rerun()
        else:
            st.info("Nothing changed.")


def show_ticket(ticket: dict) -> None:
    """One ticket as a card, with details and replies inside a fold-out section."""
    # The key gives the card a CSS class (st-key-ticket_...) so style.css can style it
    with st.container(key=f"ticket_{ticket['id']}"):
        ticket_header(ticket)
        label = "Details & manage" if admin else "Details & replies"
        # The key ties "open/closed" to this ticket, so it stays right when the list re-sorts
        with st.expander(label, icon=":material/forum:", key=f"details_{ticket['id']}"):
            ticket_conversation(ticket)
            if admin:
                admin_controls(ticket)


def empty_state(text: str) -> None:
    st.markdown(f'<div class="om-empty-state">{text}</div>', unsafe_allow_html=True)


tickets = list_tickets(user)

# ---------- Admin view ----------
if admin:
    counts = {key: sum(t["status"] == key for t in tickets) for key in STATUSES}
    st.markdown(
        '<div class="om-stats">'
        + "".join(
            f'<div class="om-stat om-stat-{key}"><span>{counts[key]}</span>{label}</div>'
            for key, label in STATUSES.items()
        )
        + "</div>",
        unsafe_allow_html=True,
    )

    # Filter buttons: All / Open / In Progress / Closed
    choice = st.segmented_control(
        "Show",
        ["all", *STATUSES],
        default="all",
        format_func=lambda key: "All" if key == "all" else STATUSES[key],
        label_visibility="collapsed",
    )
    shown = [t for t in tickets if choice in (None, "all") or t["status"] == choice]

    if not tickets:
        empty_state("🎉 No tickets yet. When employees raise one, it will appear here.")
    elif not shown:
        empty_state("No tickets with this status.")
    for ticket in shown:
        show_ticket(ticket)

# ---------- Employee view ----------
else:
    new_tab, mine_tab = st.tabs(["➕ New ticket", f"📋 My tickets ({len(tickets)})"])

    with new_tab:
        with st.form("new_ticket", clear_on_submit=True):
            title = st.text_input(
                "Title", max_chars=120, placeholder="e.g. Can't connect to office Wi-Fi"
            )
            category = st.selectbox("Category", TICKET_CATEGORIES)
            description = st.text_area(
                "Description",
                max_chars=4000,
                height=140,
                placeholder="What happened? When did it start? Any error message?",
            )
            submitted = st.form_submit_button(
                "Submit ticket", type="primary", icon=":material/send:", width="stretch"
            )
        if submitted:
            ticket_id, error = create_ticket(user, title, description, category)
            if error:
                st.error(error, icon=":material/error:")
            else:
                st.session_state.helpdesk_message = (
                    f"Ticket #{ticket_id} created. You can follow it under My tickets."
                )
                st.rerun()

    with mine_tab:
        if not tickets:
            empty_state("You haven't raised any tickets yet.")
        for ticket in tickets:
            show_ticket(ticket)
