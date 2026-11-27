"""Search results for the search box in the top bar."""

import html

import streamlit as st

from core.ui import empty_state, heading, icon, page_setup, skeleton_html, status_badge
from modules.search import search
from modules.security.masking import mask

query = st.query_params.get("q", "").strip()
user = page_setup("pages/5_Search.py", "Search", "search",
                  f"Results for “{query}”" if query else "Type in the search box at the top")

if not query:
    empty_state("search", "Search OfficeMind",
                "Find pages, tickets, onboarding tasks and passages from your company documents.")
    st.stop()

spot = st.empty()
spot.markdown(skeleton_html(lines=4, label="Searching…"), unsafe_allow_html=True)
results = search(user, query)
spot.empty()


def mark(text: str) -> str:
    """Escape text and highlight the searched words."""
    safe = html.escape(text)
    for word in sorted(set(query.split()), key=len, reverse=True):
        lower = safe.lower()
        start = lower.find(word.lower())
        if start >= 0:
            safe = safe[:start] + "<mark>" + safe[start:start + len(word)] + "</mark>" + safe[start + len(word):]
    return safe


def result(icon_name: str, title: str, text: str = "", extra: str = "") -> str:
    return (f'<div class="om-result"><div class="om-icon-tile">{icon(icon_name)}</div>'
            f'<div><div class="om-result-title">{title} {extra}</div>'
            f'<div class="om-result-text">{text}</div></div></div>')


found = sum(len(results[k]) for k in ("pages", "tickets", "documents", "passages", "tasks"))

# Ask the AI about it (opens the assistant with this question)
st.page_link("pages/1_Knowledge_Assistant.py", label=f"Ask the AI assistant: “{query}”",
             icon=":material/auto_awesome:", query_params={"ask": query})

if not found:
    empty_state("search_off", "No results",
                "Try other words, or ask the AI assistant. It searches the meaning of your documents.")
    if not results.get("ai_ok", True):
        st.caption("Document passages couldn't be searched because the AI isn't reachable (is Ollama running?).")
    st.stop()

if results["pages"]:
    heading("Pages")
    for p in results["pages"]:
        st.page_link(p["page"], label=p["label"], icon=f":material/{p['icon']}:")

if results["tickets"]:
    heading(f"Tickets ({len(results['tickets'])})")
    with st.container(key="panel_tickets"):
        st.markdown("".join(
            result("confirmation_number", f'<span class="om-ticket-id">#{t["id"]}</span>{mark(t["title"])}',
                   mark(t["description"][:160]), status_badge(t["status"], t["status_label"]))
            for t in results["tickets"]), unsafe_allow_html=True)
        st.page_link("pages/2_Helpdesk.py", label="Open Helpdesk", icon=":material/arrow_forward:")

if results["documents"] or results["passages"]:
    heading("Documents")
    with st.container(key="panel_docs"):
        rows = [result("description", mark(name), "Uploaded document") for name in results["documents"]]
        rows += [result("format_quote", f'{html.escape(p["source"])} · page {p["page"]}',
                        mark(mask(p["text"][:220])) + "…") for p in results["passages"]]
        st.markdown("".join(rows), unsafe_allow_html=True)

if results["tasks"]:
    heading(f"Onboarding tasks ({len(results['tasks'])})")
    with st.container(key="panel_tasks"):
        st.markdown("".join(
            result("check_circle" if t.get("done") else "radio_button_unchecked", mark(t["title"]),
                   f'{html.escape(t["checklist"])}' + (f' · {mark(t["description"])}' if t["description"] else ""))
            for t in results["tasks"]), unsafe_allow_html=True)
        st.page_link("pages/3_Onboarding.py", label="Open Onboarding", icon=":material/arrow_forward:")
