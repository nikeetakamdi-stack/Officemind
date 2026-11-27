"""OfficeMind home page (welcome screen). Run with:  streamlit run app.py"""

import html

import streamlit as st

from core.ui import apply_style, lottie, require_login, sidebar_menu

st.set_page_config(page_title="OfficeMind", page_icon="🧠", layout="wide")
apply_style()
user = require_login()  # not logged in? -> login page
sidebar_menu()

# ---------- Welcome box: text on the left, animation on the right ----------
text_column, animation_column = st.columns([3, 2], vertical_alignment="center")
with text_column:
    first_name = html.escape(user["full_name"].split()[0])
    st.markdown(f'<p class="om-hello">👋 Hi {first_name}</p>', unsafe_allow_html=True)
    st.markdown(
        """
        <div class="om-hero-title">Welcome to <span class="om-gradient">OfficeMind</span></div>
        <p class="om-hero-text">
          Your private AI workplace assistant. Upload company documents and get
          clear answers in seconds. Everything runs on your own computer.
        </p>
        """,
        unsafe_allow_html=True,
    )
    st.write("")
    st.page_link(
        "pages/1_Knowledge_Assistant.py",
        label="Start asking questions",
        icon=":material/arrow_forward:",
    )
with animation_column:
    lottie("welcome.json", height=280, key="welcome_animation")

st.write("")
st.markdown("### Modules")

# ---------- Module cards (two per row) ----------
MODULES = [
    ("📚", "Knowledge Assistant", "Ask questions about your PDFs and see the exact source.", True),
    ("🎧", "Helpdesk", "Answer common IT and HR questions automatically.", False),
    ("🚀", "Onboarding", "Guide new team members through their first weeks.", False),
    ("📊", "Dashboard", "See how OfficeMind is used across the team.", False),
]

for row_start in range(0, len(MODULES), 2):
    columns = st.columns(2)
    for column, (icon, title, text, ready) in zip(columns, MODULES[row_start : row_start + 2]):
        # The key gives the box a CSS class (st-key-card_...) so style.css can style it as a card
        key = f"card_{title.lower().replace(' ', '_')}" if ready else f"card_soon_{title.lower()}"
        with column.container(key=key):
            st.markdown(
                f"""
                <div class="om-card-icon">{icon}</div>
                <p class="om-card-title">{title}</p>
                <p class="om-card-text">{text}</p>
                """,
                unsafe_allow_html=True,
            )
            if ready:
                st.page_link(
                    "pages/1_Knowledge_Assistant.py", label="Open", icon=":material/open_in_new:"
                )
            else:
                st.markdown('<span class="om-badge">Coming soon</span>', unsafe_allow_html=True)
