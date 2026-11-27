"""Knowledge Assistant page: upload PDFs (admins) in the sidebar, chat in the middle."""

import html

import streamlit as st

from core.ui import (
    AI_OFFLINE,
    THINKING_HTML,
    friendly_error,
    icon,
    page_setup,
    section_title,
    sources_html,
    typing_effect,
)
from core.config import DEPARTMENTS
from modules.knowledge.assistant import (
    add_pdf,
    ask,
    delete_document,
    list_document_info,
    set_document_access,
)
from modules.knowledge.question_log import log_question
from modules.security.access import ACCESS_ICONS, ACCESS_LEVELS, can_open
from modules.security.secure_mode import confidential_allowed

user = page_setup(
    "pages/1_Knowledge_Assistant.py", "Knowledge Assistant", "menu_book",
    "Ask questions about your company documents. Answers come only from the uploaded PDFs.",
)
admin = user["role"] == "admin"


def show_sources(sources):
    """Show the files (and pages) an answer was based on, as small chips."""
    if sources:
        st.markdown(sources_html(sources), unsafe_allow_html=True)


def access_badge(info: dict) -> str:
    """Small badge: Public / Department-only (HR) / Confidential."""
    label = ACCESS_LEVELS[info["access"]]
    if info["access"] == "department" and info["department"]:
        label = info["department"] + " only"
    return (f'<span class="om-badge om-access-{info["access"]}">'
            f'{icon(ACCESS_ICONS[info["access"]])}{html.escape(label)}</span>')


def access_picker(key: str, current: str = "public", current_department: str | None = None):
    """Access level (and department, for Department-only). Returns (access, department)."""
    levels = list(ACCESS_LEVELS)
    access = st.selectbox("Who can see it?", levels, index=levels.index(current),
                          format_func=ACCESS_LEVELS.get, key=f"access_{key}")
    department = None
    if access == "department":
        department = st.selectbox("Department", DEPARTMENTS, key=f"dept_{key}",
                                  index=DEPARTMENTS.index(current_department)
                                  if current_department in DEPARTMENTS else 0)
    return access, department


# ---------- Sidebar: documents ----------
with st.sidebar:
    # Upload: admins only. For employees this part is never built, so it can't be used,
    # and add_pdf() itself refuses anyone who isn't an admin.
    if admin:
        section_title("Upload documents")
        files = st.file_uploader(
            "Choose PDF files", type="pdf", accept_multiple_files=True, label_visibility="collapsed"
        )
        upload_access, upload_department = access_picker("upload")
        if st.button("Add to knowledge base", icon=":material/upload:", type="primary",
                     width="stretch", disabled=not files):
            for file in files:
                with st.spinner(f"Reading {file.name}..."):
                    try:
                        count = add_pdf(file, file.name, user, upload_access, upload_department)
                    except Exception as error:
                        friendly_error(f"Couldn't add {file.name}", AI_OFFLINE[1], str(error))
                        continue
                if count:
                    st.success(f"{file.name} added ({count} sections).", icon=":material/check_circle:")
                else:
                    st.warning(f"{file.name} has no readable text. It may be a scanned image.",
                               icon=":material/warning:")

    section_title("Knowledge base")

    # Show the "deleted" message saved before the page refreshed
    if "deleted_message" in st.session_state:
        st.success(st.session_state.pop("deleted_message"), icon=":material/check_circle:")

    # Employees only see the documents they're allowed to see
    documents = [d for d in list_document_info() if can_open(user, d["access"], d["department"])]
    if documents and not admin:
        for info in documents:
            safe_name = html.escape(info["name"])
            st.markdown(f'<div class="om-doc-row" title="{safe_name}">{icon("description", 16)} {safe_name}'
                        f'<br>{access_badge(info)}</div>', unsafe_allow_html=True)
        st.caption("Only admins can add or remove documents.")
    elif documents:
        for number, info in enumerate(documents):
            name = info["name"]
            # The key gives this box a CSS class (st-key-doc_0, ...) so it looks like a card
            with st.container(key=f"doc_{number}"):
                name_column, menu_column, button_column = st.columns([5, 1, 1], vertical_alignment="center")
                safe_name = html.escape(name)
                name_column.markdown(f'<p title="{safe_name}">{icon("description", 16)} {safe_name}</p>'
                                     f'{access_badge(info)}', unsafe_allow_html=True)
                # Change who can see it
                with menu_column.popover("", icon=":material/shield:", help="Change who can see it"):
                    new_access, new_department = access_picker(f"doc_{number}", info["access"], info["department"])
                    if st.button("Save", key=f"save_access_{number}", type="primary"):
                        set_document_access(user, name, new_access, new_department)
                        st.session_state.deleted_message = f"Access for {name} updated"
                        st.rerun()
                # Each button needs its own key, so Streamlit can tell them apart
                if button_column.button("", icon=":material/delete:", key=f"delete_{name}",
                                        help=f"Delete {name}", type="tertiary"):
                    delete_document(name, user)
                    st.session_state.deleted_message = f"Deleted {name}"
                    st.rerun()  # refresh the page so the list updates
    else:
        st.caption("No documents yet." + (" Upload a PDF above." if admin else ""))


# ---------- Chat ----------
# st.session_state remembers the chat while the page is open
if "knowledge_messages" not in st.session_state:
    st.session_state.knowledge_messages = []
messages = st.session_state.knowledge_messages

question = st.chat_input("Ask about your documents…")

# A question sent from the search box ("Ask the AI assistant") arrives in the address
if not question and st.query_params.get("ask"):
    question = st.query_params["ask"]
    del st.query_params["ask"]

# Welcome screen when the chat is still empty
if not messages and not question:
    intro = ("Upload a PDF in the sidebar, then ask anything about it."
             if admin else "Ask anything about your company documents.")
    hints = "".join(f'<span class="om-hint">{h}</span>' for h in (
        "How many leave days do I get?", "What is the travel policy?", "Who do I contact for IT help?"))
    st.markdown(
        f"""
        <div class="om-welcome">
          <div class="om-icon-tile">{icon("auto_awesome")}</div>
          <h3>How can I help today?</h3>
          <p>{intro} Every answer shows which file and page it comes from.</p>
          <div class="om-hints">{hints}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# Earlier messages (shown straight away, no typing effect).
# Each message is built inside one box (container), the same way as a new answer,
# so nothing "jumps" or shows twice when the page updates.
for message in messages:
    with st.chat_message(message["role"]):
        with st.container():
            st.markdown(message["content"])
            show_sources(message.get("sources"))

if question:
    messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        with st.container():
            st.markdown(question)

    with st.chat_message("assistant"):
        # One spot that first shows grey "loading" lines, then the answer
        spot = st.empty()
        spot.markdown(THINKING_HTML, unsafe_allow_html=True)
        try:
            answer, sources = ask(question, user, include_confidential=confidential_allowed(user))
            # Remember the question for the Dashboard (answered = it found sources)
            log_question(user, question, answered=bool(sources), page="knowledge")
        except Exception:
            answer, sources = f"**{AI_OFFLINE[0]}.** {AI_OFFLINE[1]}", []

        with spot.container():
            # Type the answer out word by word, then show the sources
            st.write_stream(typing_effect(answer))
            show_sources(sources)

    messages.append({"role": "assistant", "content": answer, "sources": sources})
