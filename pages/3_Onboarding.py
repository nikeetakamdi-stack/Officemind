"""Onboarding page.

Admins: build checklists, assign them to new employees, see everyone's progress (and who is stuck).
Employees: tick off their checklist, watch the progress bar fill up, and ask the AI assistant.
"""

import html

import streamlit as st

from core.config import ONBOARDING_STUCK_DAYS
from core.ui import (
    AI_OFFLINE,
    THINKING_HTML,
    data_table,
    empty_state,
    heading,
    icon,
    onboarding_badge,
    page_setup,
    progress_cell,
    sources_html,
    stat_cards,
    typing_effect,
)
from modules.knowledge.assistant import ask, document_path, list_documents
from modules.knowledge.question_log import log_question
from modules.onboarding.checklists import (
    STATUSES,
    add_task,
    assign_checklist,
    assigned_user_ids,
    create_checklist,
    days_ago_text,
    delete_checklist,
    delete_task,
    list_checklists,
    list_employees,
    list_tasks,
    my_onboarding,
    progress_overview,
    set_task_done,
)

user = page_setup(
    "pages/3_Onboarding.py", "Onboarding", "task_alt",
    "Build onboarding checklists, give them to new team members and see how everyone is doing."
    if (st.session_state.get("user") or {}).get("role") == "admin"
    else "Your first steps at the company. Tick tasks off as you go, and ask the assistant anything.",
)
admin = user["role"] == "admin"

# A message saved before the page refreshed (e.g. "Checklist created")
if "onboarding_message" in st.session_state:
    st.success(st.session_state.pop("onboarding_message"), icon=":material/check_circle:")


def done_and_refresh(message: str) -> None:
    st.session_state.onboarding_message = message
    st.rerun()


# =====================================================================
# ADMIN
# =====================================================================
def progress_tab() -> None:
    rows = progress_overview(user)
    if not rows:
        empty_state("group_add", "Nobody is onboarding yet",
                    "Create a checklist, then give it to new team members in the Assign tab.")
        return

    counts = {key: sum(r["status"] == key for r in rows) for key in STATUSES}
    stat_cards([
        {"icon": "assignment_ind", "label": "Assigned", "value": len(rows), "note": "checklists given out"},
        {"icon": "check_circle", "label": "Completed", "value": counts["completed"], "note": "all tasks done",
         "tone": "green"},
        {"icon": "trending_up", "label": "In progress", "value": counts["on_track"] + counts["not_started"],
         "note": "still working on it"},
        {"icon": "error", "label": "Stuck", "value": counts["stuck"],
         "note": f"idle {ONBOARDING_STUCK_DAYS}+ days", "tone": "red" if counts["stuck"] else "green"},
    ])

    # Who is stuck: a short list on top, so it's the first thing the admin sees
    stuck = [r for r in rows if r["status"] == "stuck"]
    if stuck:
        items = "".join(
            f"""<li><strong>{html.escape(r['employee'])}</strong> · {html.escape(r['checklist'])}
                <span>{r['done']}/{r['total']} done · no progress for {r['days_idle']} days</span></li>"""
            for r in stuck
        )
        st.markdown(
            f"""
            <div class="om-ai-card om-ai-stuck">
              <div class="om-ai-title">{icon("error")} Needs a nudge</div>
              <ul class="om-stuck-list">{items}</ul>
              <p>Stuck = not finished and nothing ticked for {ONBOARDING_STUCK_DAYS} days or more.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Everyone's progress in a table
    heading("Everyone's progress")
    data_table(
        ["Employee", "Checklist", "Progress", "Done", "Last activity", "Status"],
        [
            [
                f"<strong>{html.escape(r['employee'])}</strong>",
                html.escape(r["checklist"]),
                progress_cell(r["percent"]),
                f"{r['done']}/{r['total']}",
                days_ago_text(r["days_idle"]),
                onboarding_badge(r["status"], STATUSES[r["status"]]),
            ]
            for r in rows
        ],
    )


def checklist_card(checklist: dict, documents: list[str]) -> None:
    """One checklist: its tasks (with delete buttons), a form to add a task, and delete."""
    with st.container(key=f"checklist_{checklist['id']}"):
        description = (
            f'<p class="om-card-text">{html.escape(checklist["description"])}</p>'
            if checklist["description"]
            else ""
        )
        st.markdown(
            f"""
            <div class="om-ticket-top">
              <span class="om-ticket-title">{html.escape(checklist['name'])}</span>
              <span class="om-badge">{checklist['task_count']} tasks · assigned to {checklist['assigned_count']}</span>
            </div>
            {description}
            """,
            unsafe_allow_html=True,
        )
        with st.expander("Tasks", icon=":material/checklist:", key=f"tasks_{checklist['id']}"):
            tasks = list_tasks(checklist["id"])
            if not tasks:
                st.caption("No tasks yet. Add the first one below.")
            for number, task in enumerate(tasks, start=1):
                text_column, button_column = st.columns([12, 1], vertical_alignment="center")
                doc = f" · 📄 {html.escape(task['document'])}" if task["document"] else ""
                text_column.markdown(
                    f"""<div class="om-task-line"><strong>{number}. {html.escape(task['title'])}</strong>
                        <span>{html.escape(task['description'])}{doc}</span></div>""",
                    unsafe_allow_html=True,
                )
                if button_column.button(
                    "", icon=":material/delete:", key=f"del_task_{task['id']}",
                    help="Delete this task", type="tertiary",
                ):
                    delete_task(user, task["id"])
                    done_and_refresh(f"Task deleted from “{checklist['name']}”.")

            with st.form(f"add_task_{checklist['id']}", clear_on_submit=True):
                st.markdown("**Add a task**")
                title = st.text_input("Title", max_chars=120, placeholder="e.g. Read the leave policy")
                description = st.text_area(
                    "Short description", max_chars=1000, height=70,
                    placeholder="e.g. Learn how many days off you get and how to request them.",
                )
                document = st.selectbox(
                    "Related document (optional)", ["— None —", *documents],
                    help="Pick one of the PDFs uploaded in the Knowledge Assistant.",
                )
                added = st.form_submit_button("Add task", icon=":material/add:", type="primary")
            if added:
                error = add_task(
                    user, checklist["id"], title, description,
                    None if document == "— None —" else document,
                )
                if error:
                    st.error(error, icon=":material/error:")
                else:
                    done_and_refresh(f"Task added to “{checklist['name']}”.")

        with st.popover("Delete checklist", icon=":material/delete:"):
            st.write(
                f"Delete **{checklist['name']}**, its tasks and everyone's progress on it? "
                "This can't be undone."
            )
            if st.button("Yes, delete it", key=f"del_checklist_{checklist['id']}", type="primary"):
                delete_checklist(user, checklist["id"])
                done_and_refresh(f"Checklist “{checklist['name']}” deleted.")


def checklists_tab() -> None:
    with st.form("new_checklist", clear_on_submit=True):
        st.markdown("**New checklist**")
        name = st.text_input("Name", max_chars=80, placeholder="e.g. First week at the office")
        description = st.text_area(
            "Description (optional)", max_chars=1000, height=70,
            placeholder="e.g. Everything a new team member should do in their first week.",
        )
        created = st.form_submit_button(
            "Create checklist", icon=":material/playlist_add:", type="primary"
        )
    if created:
        checklist_id, error = create_checklist(user, name, description)
        if error:
            st.error(error, icon=":material/error:")
        else:
            done_and_refresh("Checklist created. Open “Tasks” on it to add tasks.")

    checklists = list_checklists()
    if not checklists:
        empty_state("playlist_add", "No checklists yet", "Create your first checklist above.")
        return
    documents = list_documents()
    for checklist in checklists:
        checklist_card(checklist, documents)


def assign_tab() -> None:
    checklists = list_checklists()
    employees = list_employees()
    if not checklists:
        empty_state("playlist_add", "No checklists to assign", "Create a checklist first, in the Checklists tab.")
        return
    if not employees:
        empty_state("person_search", "No employees yet",
                    "People who create an account become employees automatically.")
        return

    checklist = st.selectbox(
        "Checklist", checklists,
        format_func=lambda c: f"{c['name']} ({c['task_count']} tasks)",
    )
    already = assigned_user_ids(checklist["id"])
    available = [e for e in employees if e["id"] not in already]
    names = {e["id"]: f"{e['full_name']} (@{e['username']})" for e in employees}

    if already:
        st.caption("Already assigned: " + ", ".join(names[i] for i in already if i in names))
    if not available:
        st.info("Every employee already has this checklist.", icon=":material/info:")
        return

    with st.form("assign_form", clear_on_submit=True):
        chosen = st.multiselect(
            "New employees", [e["id"] for e in available], format_func=names.get,
            placeholder="Choose one or more people",
        )
        assigned = st.form_submit_button("Assign", icon=":material/person_add:", type="primary")
    if assigned:
        if not chosen:
            st.warning("Choose at least one person.", icon=":material/warning:")
        else:
            count = assign_checklist(user, checklist["id"], chosen)
            done_and_refresh(
                f"“{checklist['name']}” assigned to {count} {'person' if count == 1 else 'people'}."
            )


# =====================================================================
# EMPLOYEE
# =====================================================================
def progress_bar(assignment: dict) -> None:
    """Progress bar that slides from the old value to the new one."""
    total, done = assignment["total"], assignment["done"]
    percent = round(100 * done / total) if total else 0
    key = f"last_percent_{assignment['id']}"
    previous = st.session_state.get(key, 0)
    st.session_state[key] = percent
    st.markdown(
        f"""
        <div class="om-progress-head">
          <span><strong>{done}/{total}</strong> done</span><span>{percent}%</span>
        </div>
        <div class="om-progress">
          <div class="om-progress-fill" style="--from:{previous}%; --to:{percent}%"></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


CONFETTI_COLORS = ["#1F4FB5", "#5B8DEF", "#17B26A", "#F79009"]  # brand blues + status colours


def celebration(show_confetti: bool) -> None:
    """The "all done" card. A few confetti pieces only right after the last task is ticked."""
    confetti = ""
    if show_confetti:
        confetti = "".join(
            f'<i style="--x:{(i * 37) % 100}%; --d:{(i % 6) * 0.06:.2f}s; '
            f'--r:{(i * 47) % 360}deg; --c:{CONFETTI_COLORS[i % len(CONFETTI_COLORS)]}"></i>'
            for i in range(16)
        )
    st.markdown(
        f"""
        <div class="om-celebrate">
          <div class="om-confetti">{confetti}</div>
          <div class="om-icon-tile">{icon("celebration")}</div>
          <div><strong>All done. Welcome aboard!</strong>
          <p>You've finished every task on this checklist.</p></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def on_tick(assignment_id: int, task_id: int) -> None:
    """Runs when a checkbox is clicked: save it, and celebrate if that was the last task."""
    done = st.session_state[f"tick_{assignment_id}_{task_id}"]
    if set_task_done(user, assignment_id, task_id, done):
        st.session_state.celebrate = assignment_id
        st.toast("Onboarding complete. Welcome aboard!", icon=":material/celebration:")


def task_row(assignment: dict, task: dict) -> None:
    # The key includes "done"/"todo", so the card is redrawn (and animates) when it changes
    state = "done" if task["done"] else "todo"
    with st.container(key=f"task_{assignment['id']}_{task['id']}_{state}"):
        st.checkbox(
            task["title"],
            value=task["done"],
            key=f"tick_{assignment['id']}_{task['id']}",
            on_change=on_tick,
            args=(assignment["id"], task["id"]),
        )
        if task["description"]:
            st.markdown(
                f'<div class="om-task-desc">{html.escape(task["description"])}</div>',
                unsafe_allow_html=True,
            )
        if task["document"]:
            path = document_path(task["document"])
            if path.exists():
                st.download_button(
                    f"Open {task['document']}",
                    data=path.read_bytes(),
                    file_name=task["document"],
                    mime="application/pdf",
                    icon=":material/description:",
                    key=f"doc_{assignment['id']}_{task['id']}",
                    type="tertiary",
                )
            else:
                st.markdown(
                    f'<div class="om-task-desc">{icon("description", 16)} Related document: {html.escape(task["document"])} '
                    "(ask the assistant below about it)</div>",
                    unsafe_allow_html=True,
                )


def employee_checklists() -> None:
    assignments = my_onboarding(user)
    if not assignments:
        empty_state("event_available", "No onboarding checklist yet",
                    "Your admin will assign one to you. Meanwhile, ask the assistant below anything.")
        return

    celebrate = st.session_state.pop("celebrate", None)
    for assignment in assignments:
        with st.container(key=f"assignment_{assignment['id']}"):
            st.markdown(
                f'<div class="om-ticket-title">{html.escape(assignment["name"])}</div>'
                + (
                    f'<p class="om-card-text">{html.escape(assignment["description"])}</p>'
                    if assignment["description"]
                    else ""
                ),
                unsafe_allow_html=True,
            )
            progress_bar(assignment)
            if assignment["total"] and assignment["done"] == assignment["total"]:
                celebration(show_confetti=celebrate == assignment["id"])
            for task in assignment["tasks"]:
                task_row(assignment, task)


def assistant_chat() -> None:
    """Ask questions about the company documents, right here on the onboarding page."""
    heading("Ask the assistant")
    st.markdown(
        '<p class="om-muted">Questions about your first weeks? The answers come from the company documents.</p>',
        unsafe_allow_html=True,
    )
    if "onboarding_messages" not in st.session_state:
        st.session_state.onboarding_messages = []
    messages = st.session_state.onboarding_messages

    for message in messages:
        with st.chat_message(message["role"]):
            with st.container():
                st.markdown(message["content"])
                if message.get("sources"):
                    st.markdown(sources_html(message["sources"]), unsafe_allow_html=True)

    question = st.chat_input("Ask about policies, tools, your first week…")
    if question:
        messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            with st.container():
                st.markdown(question)
        with st.chat_message("assistant"):
            spot = st.empty()
            spot.markdown(THINKING_HTML, unsafe_allow_html=True)
            try:
                answer, sources = ask(question)
                log_question(user, question, answered=bool(sources), page="onboarding")
            except Exception:
                answer, sources = f"**{AI_OFFLINE[0]}.** {AI_OFFLINE[1]}", []
            with spot.container():
                st.write_stream(typing_effect(answer))
                if sources:
                    st.markdown(sources_html(sources), unsafe_allow_html=True)
        messages.append({"role": "assistant", "content": answer, "sources": sources})


# =====================================================================
if admin:
    progress, checklists, assign = st.tabs(
        [":material/insights: Progress", ":material/checklist: Checklists", ":material/person_add: Assign"]
    )
    with progress:
        progress_tab()
    with checklists:
        checklists_tab()
    with assign:
        assign_tab()
else:
    employee_checklists()
    assistant_chat()
