"""Shared look & feel for every OfficeMind page: styles, sidebar menu and animations."""

import html
import json
import re
import time
from pathlib import Path

import streamlit as st
from streamlit_lottie import st_lottie

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
LOGIN_PAGE = "pages/0_Login.py"


# ---------- Who is logged in ----------
def current_user() -> dict | None:
    """The logged-in user (id, username, full_name, role), or None."""
    return st.session_state.get("user")


def require_login() -> dict:
    """Send visitors who are not logged in to the login page. Call at the top of every page."""
    user = current_user()
    if user is None:
        st.switch_page(LOGIN_PAGE)  # stops this page here
    return user


def is_admin() -> bool:
    user = current_user()
    return user is not None and user["role"] == "admin"


def log_out() -> None:
    """Forget the user and their chat, then go back to the login page."""
    st.session_state.clear()
    st.switch_page(LOGIN_PAGE)


def apply_style() -> None:
    """Load assets/style.css into the page. Call this at the top of every page."""
    css = (ASSETS_DIR / "style.css").read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def sidebar_menu() -> None:
    """Draw the OfficeMind logo and the menu with icons at the top of the sidebar."""
    with st.sidebar:
        st.markdown(
            '<div class="om-brand"><span class="om-brand-logo">🧠</span>OfficeMind</div>',
            unsafe_allow_html=True,
        )
        st.page_link("app.py", label="Home", icon=":material/home:")
        st.page_link(
            "pages/1_Knowledge_Assistant.py",
            label="Knowledge Assistant",
            icon=":material/menu_book:",
        )
        st.page_link("pages/2_Helpdesk.py", label="Helpdesk", icon=":material/support_agent:")
        st.page_link("pages/3_Onboarding.py", label="Onboarding", icon=":material/rocket_launch:")
        if is_admin():  # the dashboard is for admins only
            st.page_link("pages/4_Dashboard.py", label="Dashboard", icon=":material/monitoring:")

        user = current_user()
        if user:
            name = html.escape(user["full_name"])
            initial = html.escape(user["full_name"][:1].upper())
            role = user["role"]
            st.markdown(
                f"""
                <div class="om-user">
                  <span class="om-avatar">{initial}</span>
                  <span class="om-user-text">
                    <span class="om-user-name">{name}</span>
                    <span class="om-role om-role-{role}">{role.title()}</span>
                  </span>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button("Log out", icon=":material/logout:", key="logout", width="stretch"):
                log_out()


def section_title(text: str) -> None:
    """Small grey uppercase title, used to split the sidebar into sections."""
    st.markdown(f'<div class="om-section">{html.escape(text)}</div>', unsafe_allow_html=True)


@st.cache_data
def _load_lottie(name: str) -> dict:
    return json.loads((ASSETS_DIR / name).read_text(encoding="utf-8"))


def lottie(name: str, height: int, key: str) -> None:
    """Play a Lottie animation saved in the assets folder (loops forever)."""
    st_lottie(_load_lottie(name), height=height, key=key, loop=True)


def typing_effect(text: str, delay: float = 0.025):
    """Give back the text a word at a time, so st.write_stream "types" it out."""
    for piece in re.split(r"(\s+)", text):  # keep spaces and line breaks
        yield piece
        if piece.strip():
            time.sleep(delay)


def thinking_html(text: str) -> str:
    """Three bouncing dots with a short message, shown while the AI is working."""
    return f"""
<div class="om-thinking">
  <span class="om-dots"><span></span><span></span><span></span></span>
  <span>{html.escape(text)}</span>
</div>
"""


THINKING_HTML = thinking_html("Searching your documents…")


STATUS_ICONS = {"open": "●", "in_progress": "◐", "closed": "✓"}


def status_badge(status: str, label: str) -> str:
    """Coloured pill for a ticket status: red Open, yellow In Progress, green Closed."""
    icon = STATUS_ICONS.get(status, "●")
    return f'<span class="om-status om-status-{status}">{icon} {html.escape(label)}</span>'


URGENCY_ICONS = {"high": "🔥", "medium": "⚡", "low": "🌱"}


def urgency_tag(urgency: str, label: str, title: str = "") -> str:
    """Coloured tag for urgency: High, Medium or Low. `title` shows when you hover over it."""
    icon = URGENCY_ICONS.get(urgency, "⚡")
    hover = f' title="{html.escape(title)}"' if title else ""
    return (
        f'<span class="om-urgency om-urgency-{urgency}"{hover}>'
        f"{icon} {html.escape(label)}</span>"
    )


def sources_html(sources: list[dict]) -> str:
    """Turn [{"source": file, "page": n}, ...] into small rounded "chips"."""
    chips = "".join(
        f'<span class="om-chip">📄 {html.escape(s["source"])} · page {s["page"]}</span>'
        for s in sources
    )
    return f'<div class="om-sources">{chips}</div>'
