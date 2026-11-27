"""Login and sign-up page. Everyone who is not logged in is sent here."""

import streamlit as st

from core.auth import PASSWORD_RULES, attempt_login, count_users, sign_up
from core.config import DEPARTMENTS, IDLE_TIMEOUT_MINUTES
from core.ui import LOGO_PNG, apply_style, brand_html, current_user, icon

st.set_page_config(page_title="Sign in · OfficeMind", page_icon=LOGO_PNG, layout="wide")
apply_style()

# No sidebar and no top bar on this page: there is nothing to open until you sign in
st.markdown(
    """
    <style>
      [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"],
      [data-testid="stExpandSidebarButton"] { display: none; }
      [data-testid="stMainBlockContainer"] { max-width: 1120px; padding-top: 3rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

# Already logged in? Go straight to the home page.
if current_user():
    st.switch_page("app.py")


def start_session(user: dict) -> None:
    """Remember the user for this browser tab and open the home page."""
    st.session_state.user = user
    st.switch_page("app.py")


FEATURES = [
    ("menu_book", "Knowledge Assistant", "Answers from your company documents, with sources."),
    ("support_agent", "Smart Helpdesk", "AI suggests the category, urgency and a possible fix."),
    ("task_alt", "Guided onboarding", "Checklists that help new people settle in fast."),
]

brand_column, form_column = st.columns([1.05, 1], gap="large")

# ---------- Left: brand panel ----------
with brand_column:
    features = "".join(
        f'<div class="om-login-feature">{icon(name)}<div><strong>{title}</strong>'
        f"<small>{text}</small></div></div>"
        for name, title, text in FEATURES
    )
    st.markdown(
        f"""
        <div class="om-login-brand">
          {brand_html(size=36, tag=False)}
          <div class="om-login-headline">Your private AI workplace assistant</div>
          <p class="om-login-text">Everything runs on your own computer: your documents and
          conversations never leave it.</p>
          {features}
        </div>
        """,
        unsafe_allow_html=True,
    )

# ---------- Right: sign-in card with two tabs ----------
with form_column, st.container(key="auth_card"):
    st.markdown(
        '<div class="om-auth-title">Welcome</div>'
        '<p class="om-auth-sub">Sign in to your account, or create one.</p>',
        unsafe_allow_html=True,
    )
    if st.query_params.get("reason") == "idle":
        st.info(f"You were signed out after {IDLE_TIMEOUT_MINUTES} minutes without activity, "
                "to keep company data safe. Please sign in again.", icon=":material/timer_off:")
    login_tab, signup_tab = st.tabs(["Sign in", "Create account"])

    with login_tab:
        with st.form("login_form"):
            username = st.text_input("Username", placeholder="e.g. priya.sharma")
            password = st.text_input("Password", type="password")
            log_in_clicked = st.form_submit_button(
                "Sign in", type="primary", icon=":material/login:", width="stretch"
            )
        if log_in_clicked:
            with st.spinner("Checking..."):
                user, message = attempt_login(username, password)
            if user:
                start_session(user)
            else:
                st.error(message, icon=":material/lock:" if "locked" in message else ":material/error:")

    with signup_tab:
        if count_users() == 0:
            st.info(
                "You're the first person here, so your account will be the **admin**. "
                "Everyone who signs up after you will be an employee.",
                icon=":material/shield_person:",
            )
        with st.form("signup_form"):
            full_name = st.text_input("Full name", placeholder="e.g. Priya Sharma")
            new_username = st.text_input(
                "Username", placeholder="e.g. priya.sharma", key="signup_username"
            )
            email = st.text_input("Work email", placeholder="e.g. priya@company.com")
            department = st.selectbox("Department", DEPARTMENTS)
            new_password = st.text_input(
                "Password", type="password", help=PASSWORD_RULES, key="signup_password"
            )
            st.caption(PASSWORD_RULES)
            confirm_password = st.text_input("Confirm password", type="password")
            sign_up_clicked = st.form_submit_button(
                "Create account", type="primary", icon=":material/person_add:", width="stretch"
            )
        if sign_up_clicked:
            if new_password != confirm_password:
                st.error("The two passwords don't match.", icon=":material/error:")
            else:
                with st.spinner("Creating your account..."):
                    user, error = (None, "Please enter your work email.") if not email.strip() else sign_up(full_name, new_username, new_password, department, email)
                if error:
                    st.error(error, icon=":material/error:")
                else:
                    start_session(user)
