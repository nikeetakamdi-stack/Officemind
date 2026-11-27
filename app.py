"""OfficeMind home page (shown after signing in). Run with:  streamlit run app.py"""

import html
from datetime import datetime

import streamlit as st

from core.ui import heading, icon, page_setup, skeleton_html, stat_cards
from modules.home import home_stats

user = page_setup("app.py", "Home", "home", header=False)  # the greeting is the title here

# ---------- Welcome ----------
hour = datetime.now().hour
greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
first_name = html.escape(user["full_name"].split()[0])
st.markdown(
    f"""
    <p class="om-hello">{datetime.now():%A, %d %B}</p>
    <div class="om-hero-title">{greeting}, {first_name}</div>
    <p class="om-hero-text">Here's what's happening in your workspace today.</p>
    """,
    unsafe_allow_html=True,
)

# ---------- Quick stats (grey placeholders first, while the numbers load) ----------
stats_spot = st.empty()
stats_spot.markdown(
    '<div class="om-kpis">' + skeleton_html(lines=2, title=False) * 4 + "</div>",
    unsafe_allow_html=True,
)
with stats_spot.container():
    stat_cards(home_stats(user))

# ---------- Shortcuts to each module ----------
heading("Your workspace")

# (icon, title, description, page, admin only)
MODULES = [
    ("menu_book", "Knowledge Assistant", "Ask questions about company documents and see the exact source.",
     "pages/1_Knowledge_Assistant.py", False),
    ("support_agent", "Helpdesk", "Raise IT tickets and follow them until they're solved.",
     "pages/2_Helpdesk.py", False),
    ("task_alt", "Onboarding", "Checklists that guide new team members through their first weeks.",
     "pages/3_Onboarding.py", False),
    ("monitoring", "Dashboard", "Tickets, onboarding and AI questions at a glance, with Excel export.",
     "pages/4_Dashboard.py", True),
]
visible = [m for m in MODULES if not m[4] or user["role"] == "admin"]

columns = st.columns(len(visible))
for column, (icon_name, title, text, page, _) in zip(columns, visible):
    # The key gives the box a CSS class (st-key-card_...) so style.css draws it as a card
    with column.container(key=f"card_{icon_name}"):
        st.markdown(
            f"""
            <div class="om-shortcut-head"><div class="om-icon-tile">{icon(icon_name)}</div>
            <div class="om-card-title">{title}</div></div>
            <p class="om-card-text">{text}</p>
            """,
            unsafe_allow_html=True,
        )
        st.page_link(page, label="Open", icon=":material/arrow_forward:")
