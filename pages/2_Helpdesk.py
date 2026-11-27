"""Helpdesk page.

Employees: describe a problem, review the AI's suggestions, raise the ticket, and follow it.
Admins: see every ticket (High urgency first), change its status and reply.
"""

import html

import streamlit as st

from core.config import TICKET_CATEGORIES
from core.ui import (
    AI_OFFLINE,
    empty_state,
    icon,
    page_setup,
    skeleton_html,
    stat_cards,
    status_badge,
    urgency_tag,
)
from modules.helpdesk.ai import analyze_ticket
from modules.helpdesk.tickets import (
    STATUSES,
    URGENCIES,
    add_reply,
    check_ticket_text,
    create_ticket,
    friendly_time,
    list_replies,
    list_tickets,
    update_status,
)

user = page_setup(
    "pages/2_Helpdesk.py", "Helpdesk", "support_agent",
    "Every ticket from your team. Update the status and reply to keep people informed."
    if (st.session_state.get("user") or {}).get("role") == "admin"
    else "Having a problem? Raise a ticket and follow its progress here.",
)
admin = user["role"] == "admin"

# A message saved before the page refreshed (e.g. "Ticket #4 created")
if "helpdesk_message" in st.session_state:
    st.success(st.session_state.pop("helpdesk_message"), icon=":material/check_circle:")


# ---------- Building blocks ----------
def ticket_header(ticket: dict) -> None:
    """Top of a ticket card: number, title, status badge and small details."""
    by = f" · by {html.escape(ticket['author'])}" if admin else ""
    replies = ticket["reply_count"]
    reply_text = f" · {icon('chat_bubble', 14)} {replies} repl{'y' if replies == 1 else 'ies'}" if replies else ""

    # Urgency tag. ✨ = the AI suggested it and the employee kept it.
    urgency, ai_urgency = ticket["urgency"], ticket["ai_urgency"]
    if ai_urgency == urgency:
        label, hover = f"{URGENCIES[urgency]} · AI", "Suggested by the AI and kept by the employee"
    elif ai_urgency:
        label = URGENCIES[urgency]
        hover = f"AI suggested {URGENCIES[ai_urgency]}; the employee chose {URGENCIES[urgency]}"
    else:
        label, hover = URGENCIES[urgency], "Raised before AI suggestions"
    ai_note = (
        f" · AI suggested {URGENCIES[ai_urgency]}"
        if admin and ai_urgency and ai_urgency != urgency
        else ""
    )

    st.markdown(
        f"""
        <div class="om-ticket-top">
          <span class="om-ticket-title">
            <span class="om-ticket-id">#{ticket['id']}</span> {html.escape(ticket['title'])}
          </span>
          <span class="om-badges">
            {urgency_tag(urgency, label, hover)}
            {status_badge(ticket['status'], STATUSES[ticket['status']])}
          </span>
        </div>
        <div class="om-ticket-meta">
          {html.escape(ticket['category'])}{by} · {friendly_time(ticket['created_at'])}{reply_text}{ai_note}
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


# ---------- Raising a ticket (employees): step 1 describe, step 2 review ----------
# While a ticket is being written, it is kept in st.session_state["ticket_draft"]:
# {"title", "description", "analysis" (the AI's results), "step": "describe" or "review"}
DRAFT = "ticket_draft"


def describe_step() -> None:
    """Step 1: title and description, then let the AI have a look."""
    draft = st.session_state.get(DRAFT, {})
    with st.form("describe_ticket"):
        title = st.text_input(
            "Title",
            value=draft.get("title", ""),
            max_chars=120,
            placeholder="e.g. Can't connect to office Wi-Fi",
        )
        description = st.text_area(
            "Description",
            value=draft.get("description", ""),
            max_chars=4000,
            height=140,
            placeholder="What happened? When did it start? Any error message?",
        )
        check = st.form_submit_button(
            "Check with AI", type="primary", icon=":material/auto_awesome:", width="stretch"
        )
    st.caption(
        "The AI suggests a category and urgency, checks for similar tickets and looks for "
        "a possible fix. You can change everything before you submit."
    )

    if check:
        error = check_ticket_text(title, description)
        if error:
            st.error(error, icon=":material/error:")
            return
        spot = st.empty()  # grey "loading" card while the AI works
        spot.markdown(skeleton_html(lines=4, label="The AI is reading your ticket…"),
                      unsafe_allow_html=True)
        analysis = analyze_ticket(title.strip(), description.strip(), user)
        spot.empty()
        st.session_state[DRAFT] = {
            "title": title.strip(),
            "description": description.strip(),
            "analysis": analysis,
            "step": "review",
        }
        st.rerun()


def similar_card(similar: list[dict]) -> None:
    """Warning: someone already reported this problem."""
    items = "".join(
        f"""<li><span class="om-ticket-id">#{t['id']}</span> {html.escape(t['title'])}
            {status_badge(t['status'], STATUSES[t['status']])}</li>"""
        for t in similar
    )
    st.markdown(
        f"""
        <div class="om-ai-card om-ai-similar">
          <div class="om-ai-title">{icon("warning")} Similar issue already reported</div>
          <ul class="om-ai-list">{items}</ul>
          <p>If this is the same problem, the IT team is already working on it,
          so you may not need a new ticket.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def fix_card(fix: dict) -> None:
    """A possible fix, plus the original text it comes from."""
    steps = "".join(f"<li>{html.escape(step)}</li>" for step in fix["steps"])
    steps_html = f'<ol class="om-ai-steps">{steps}</ol>' if steps else ""
    evidence = "".join(
        f"""<div class="om-evidence"><span class="om-chip">{html.escape(e['label'])}</span>
            <q>{html.escape(e['text'])}</q></div>"""
        for e in fix["evidence"]
    )
    st.markdown(
        f"""
        <div class="om-ai-card om-ai-fix">
          <div class="om-ai-title">{icon("lightbulb")} Possible fix: try this first</div>
          {steps_html}
          <div class="om-ai-based">Based on</div>
          {evidence}
        </div>
        """,
        unsafe_allow_html=True,
    )


def review_step(draft: dict) -> None:
    """Step 2: show what the AI found, let the employee adjust, then submit."""
    analysis = draft["analysis"]

    with st.container(key="draft_summary"):
        st.markdown(
            f"""
            <div class="om-ticket-title">{html.escape(draft['title'])}</div>
            <div class="om-ticket-desc">{html.escape(draft['description'])}</div>
            """,
            unsafe_allow_html=True,
        )

    if analysis["problems"]:
        st.warning(f"{AI_OFFLINE[0]}, so some suggestions are missing. {AI_OFFLINE[1]} "
                   "You can still submit the ticket.", icon=":material/warning:")
    if analysis["similar"]:
        similar_card(analysis["similar"])
    if analysis["fix"]:
        fix_card(analysis["fix"])

    ai_category, ai_urgency = analysis["category"], analysis["urgency"]
    urgency_keys = list(URGENCIES)
    with st.form("confirm_ticket"):
        left, right = st.columns(2)
        category = left.selectbox(
            "Category",
            TICKET_CATEGORIES,
            index=TICKET_CATEGORIES.index(ai_category),
            format_func=lambda c: f"{c} (AI suggestion)" if c == ai_category else c,
        )
        urgency = right.selectbox(
            "Urgency",
            urgency_keys,
            index=urgency_keys.index(ai_urgency),
            format_func=lambda u: (
                f"{URGENCIES[u]} (AI suggestion)" if u == ai_urgency else URGENCIES[u]
            ),
        )
        st.caption("Suggested by the AI. Change them if they're not right.")
        submit_label = "Submit anyway" if analysis["similar"] else "Submit ticket"
        submitted = st.form_submit_button(
            submit_label, type="primary", icon=":material/send:", width="stretch"
        )

    back, cancel = st.columns(2)
    if back.button("Edit description", icon=":material/edit:", width="stretch"):
        draft["step"] = "describe"
        st.rerun()
    if cancel.button("Cancel", icon=":material/close:", width="stretch"):
        st.session_state.pop(DRAFT, None)
        st.rerun()

    if submitted:
        ticket_id, error = create_ticket(
            user, draft["title"], draft["description"], category, urgency, ai_urgency=ai_urgency
        )
        if error:
            st.error(error, icon=":material/error:")
        else:
            st.session_state.pop(DRAFT, None)
            st.session_state.helpdesk_message = (
                f"Ticket #{ticket_id} created. You can follow it under My tickets."
            )
            st.rerun()


tickets = list_tickets(user)

# ---------- Admin view ----------
if admin:
    counts = {key: sum(t["status"] == key for t in tickets) for key in STATUSES}
    stat_cards([
        {"icon": "radio_button_unchecked", "label": "Open", "value": counts["open"],
         "note": "waiting to be picked up", "tone": "red" if counts["open"] else "brand"},
        {"icon": "progress_activity", "label": "In Progress", "value": counts["in_progress"],
         "note": "being worked on", "tone": "amber" if counts["in_progress"] else "brand"},
        {"icon": "check_circle", "label": "Closed", "value": counts["closed"],
         "note": "solved", "tone": "green"},
    ])

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
        empty_state("inbox", "No tickets yet", "When employees raise a ticket, it will appear here.")
    elif not shown:
        empty_state("filter_alt_off", "No tickets with this status", "Try another filter above.")
    for ticket in shown:
        show_ticket(ticket)

# ---------- Employee view ----------
else:
    new_tab, mine_tab = st.tabs([":material/add: New ticket", f":material/list_alt: My tickets ({len(tickets)})"])

    with new_tab:
        draft = st.session_state.get(DRAFT)
        if draft and draft["step"] == "review":
            review_step(draft)
        else:
            describe_step()

    with mine_tab:
        if not tickets:
            empty_state("confirmation_number", "No tickets yet",
                        "When something isn't working, raise a ticket in the New ticket tab.")
        for ticket in tickets:
            show_ticket(ticket)
