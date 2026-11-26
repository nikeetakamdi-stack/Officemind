"""Knowledge Assistant page: upload PDFs on the left, chat on the right."""

import streamlit as st

from modules.knowledge.assistant import add_pdf, ask, delete_document, list_documents

st.set_page_config(page_title="Knowledge Assistant · OfficeMind", page_icon="📚")
st.title("📚 Knowledge Assistant")
st.caption("Ask questions about your company documents. Answers come only from the PDFs you upload.")


def show_sources(sources):
    """Print the file names (and pages) an answer was based on."""
    if sources:
        lines = [f"- {s['source']} (page {s['page']})" for s in sources]
        st.caption("**Sources**\n" + "\n".join(lines))


# ---------- Sidebar: upload PDFs ----------
with st.sidebar:
    st.header("Upload documents")
    files = st.file_uploader("Choose PDF files", type="pdf", accept_multiple_files=True)

    if st.button("Add to knowledge base", disabled=not files):
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

    st.header("In the knowledge base")

    # Show the "deleted" message saved before the page refreshed
    if "deleted_message" in st.session_state:
        st.success(st.session_state.pop("deleted_message"))

    documents = list_documents()
    if documents:
        for name in documents:
            name_column, button_column = st.columns([5, 1])
            name_column.write(f"📄 {name}")
            # Each button needs its own key, so Streamlit can tell them apart
            if button_column.button("🗑️", key=f"delete_{name}", help=f"Delete {name}"):
                delete_document(name)
                st.session_state.deleted_message = f"Deleted {name}"
                st.rerun()  # refresh the page so the list updates
    else:
        st.write("Nothing yet.")


# ---------- Chat ----------
# st.session_state remembers the chat while the page is open
if "knowledge_messages" not in st.session_state:
    st.session_state.knowledge_messages = []

for message in st.session_state.knowledge_messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        show_sources(message.get("sources"))

question = st.chat_input("Ask about your documents...")
if question:
    st.session_state.knowledge_messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Searching your documents..."):
            try:
                answer, sources = ask(question)
            except Exception as error:
                answer, sources = f"Something went wrong: {error}\n\nIs Ollama running?", []
        st.markdown(answer)
        show_sources(sources)

    st.session_state.knowledge_messages.append(
        {"role": "assistant", "content": answer, "sources": sources}
    )
