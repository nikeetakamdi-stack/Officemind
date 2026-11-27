"""Knowledge Assistant page: upload PDFs on the left, chat on the right."""

import html

import streamlit as st

from core.ui import (
    THINKING_HTML,
    apply_style,
    is_admin,
    lottie,
    require_login,
    section_title,
    sidebar_menu,
    sources_html,
    typing_effect,
)
from core.ui import current_user
from modules.knowledge.assistant import add_pdf, ask, delete_document, list_documents
from modules.knowledge.question_log import log_question

st.set_page_config(page_title="Knowledge Assistant · OfficeMind", page_icon="📚")
apply_style()
require_login()  # not logged in? -> login page
sidebar_menu()
admin = is_admin()  # True for admins, False for employees

st.markdown(
    """
    <div class="om-page-title">📚 <span class="om-gradient">Knowledge Assistant</span></div>
    <p class="om-page-subtitle">Ask questions about your company documents.
    Answers come only from the PDFs you upload.</p>
    """,
    unsafe_allow_html=True,
)


def show_sources(sources):
    """Show the files (and pages) an answer was based on, as small chips."""
    if sources:
        st.markdown(sources_html(sources), unsafe_allow_html=True)


# ---------- Sidebar ----------
with st.sidebar:
    # Upload: admins only. For employees this part is never built, so it can't be used.
    if admin:
        section_title("Upload documents")
        files = st.file_uploader(
            "Choose PDF files", type="pdf", accept_multiple_files=True, label_visibility="collapsed"
        )

        if st.button(
            "Add to knowledge base",
            icon=":material/add_circle:",
            type="primary",
            width="stretch",
            disabled=not files,
        ):
            for file in files:
                with st.spinner(f"Reading {file.name}..."):
                    try:
                        count = add_pdf(file, file.name)
                    except Exception as error:
                        st.error(f"{file.name}: {error}\n\nIs Ollama running?")
                        continue
                if count:
                    st.success(f"{file.name}: saved {count} chunks")
                else:
                    st.warning(f"{file.name}: no text found (it may be a scanned image)")

    section_title("Knowledge base")

    # Show the "deleted" message saved before the page refreshed
    if "deleted_message" in st.session_state:
        st.success(st.session_state.pop("deleted_message"), icon=":material/check_circle:")

    documents = list_documents()
    if documents and not admin:
        # Employees see the list, but without delete buttons
        for name in documents:
            safe_name = html.escape(name)
            st.markdown(
                f'<div class="om-doc-row" title="{safe_name}">📄 {safe_name}</div>',
                unsafe_allow_html=True,
            )
        st.caption("Only admins can add or remove documents.")
    elif documents:
        for number, name in enumerate(documents):
            # The key gives this box a CSS class (st-key-doc_0, ...) so it looks like a card
            with st.container(key=f"doc_{number}"):
                name_column, button_column = st.columns([5, 1], vertical_alignment="center")
                safe_name = html.escape(name)
                name_column.markdown(
                    f'<p title="{safe_name}">📄 {safe_name}</p>', unsafe_allow_html=True
                )
                # Each button needs its own key, so Streamlit can tell them apart
                if button_column.button(
                    "",
                    icon=":material/delete:",
                    key=f"delete_{name}",
                    help=f"Delete {name}",
                    type="tertiary",
                ):
                    delete_document(name)
                    st.session_state.deleted_message = f"Deleted {name}"
                    st.rerun()  # refresh the page so the list updates
    else:
        st.markdown('<p class="om-empty-docs">No documents yet.</p>', unsafe_allow_html=True)


# ---------- Chat ----------
# st.session_state remembers the chat while the page is open
if "knowledge_messages" not in st.session_state:
    st.session_state.knowledge_messages = []
messages = st.session_state.knowledge_messages

question = st.chat_input("Ask about your documents...")

# Welcome screen when the chat is still empty
if not messages and not question:
    lottie("welcome.json", height=170, key="chat_welcome")
    intro = (
        "Upload a PDF in the sidebar, then ask me anything about it."
        if admin
        else "Ask me anything about your company documents."
    )
    st.markdown(
        f"""
        <div class="om-welcome">
          <h3>How can I help today?</h3>
          <p>{intro}
          I'll show you which file and page every answer comes from.</p>
          <div class="om-hints">
            <span class="om-hint">💡 How many leave days do I get?</span>
            <span class="om-hint">💡 What is the travel policy?</span>
            <span class="om-hint">💡 Who do I contact for IT help?</span>
          </div>
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
        # One spot that first shows the bouncing dots, then the answer
        spot = st.empty()
        spot.markdown(THINKING_HTML, unsafe_allow_html=True)
        try:
            answer, sources = ask(question)
            # Remember the question for the Dashboard (answered = it found sources)
            log_question(current_user(), question, answered=bool(sources), page="knowledge")
        except Exception as error:
            answer, sources = f"Something went wrong: {error}\n\nIs Ollama running?", []

        with spot.container():
            # Type the answer out word by word, then show the sources
            st.write_stream(typing_effect(answer))
            show_sources(sources)

    messages.append({"role": "assistant", "content": answer, "sources": sources})
