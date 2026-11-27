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
from modules.knowledge.assistant import add_pdf, ask, delete_document, list_documents
from modules.knowledge.question_log import log_question

user = page_setup(
    "pages/1_Knowledge_Assistant.py", "Knowledge Assistant", "menu_book",
    "Ask questions about your company documents. Answers come only from the uploaded PDFs.",
)
admin = user["role"] == "admin"


def show_sources(sources):
    """Show the files (and pages) an answer was based on, as small chips."""
    if sources:
        st.markdown(sources_html(sources), unsafe_allow_html=True)


# ---------- Sidebar: documents ----------
with st.sidebar:
    # Upload: admins only. For employees this part is never built, so it can't be used.
    if admin:
        section_title("Upload documents")
        files = st.file_uploader(
            "Choose PDF files", type="pdf", accept_multiple_files=True, label_visibility="collapsed"
        )
        if st.button("Add to knowledge base", icon=":material/upload:", type="primary",
                     width="stretch", disabled=not files):
            for file in files:
                with st.spinner(f"Reading {file.name}..."):
                    try:
                        count = add_pdf(file, file.name)
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

    documents = list_documents()
    if documents and not admin:
        # Employees see the list, but without delete buttons
        for name in documents:
            safe_name = html.escape(name)
            st.markdown(f'<div class="om-doc-row" title="{safe_name}">{icon("description", 16)} {safe_name}</div>',
                        unsafe_allow_html=True)
        st.caption("Only admins can add or remove documents.")
    elif documents:
        for number, name in enumerate(documents):
            # The key gives this box a CSS class (st-key-doc_0, ...) so it looks like a card
            with st.container(key=f"doc_{number}"):
                name_column, button_column = st.columns([5, 1], vertical_alignment="center")
                safe_name = html.escape(name)
                name_column.markdown(f'<p title="{safe_name}">{icon("description", 16)} {safe_name}</p>',
                                     unsafe_allow_html=True)
                # Each button needs its own key, so Streamlit can tell them apart
                if button_column.button("", icon=":material/delete:", key=f"delete_{name}",
                                        help=f"Delete {name}", type="tertiary"):
                    delete_document(name)
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
            answer, sources = ask(question)
            # Remember the question for the Dashboard (answered = it found sources)
            log_question(user, question, answered=bool(sources), page="knowledge")
        except Exception:
            answer, sources = f"**{AI_OFFLINE[0]}.** {AI_OFFLINE[1]}", []

        with spot.container():
            # Type the answer out word by word, then show the sources
            st.write_stream(typing_effect(answer))
            show_sources(sources)

    messages.append({"role": "assistant", "content": answer, "sources": sources})
