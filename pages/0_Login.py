"""Login and sign-up page. Everyone who is not logged in is sent here."""

import streamlit as st

from core.auth import count_users, log_in, sign_up
from core.ui import apply_style, current_user, lottie

st.set_page_config(page_title="Log in · OfficeMind", page_icon="🧠", layout="centered")
apply_style()

# No sidebar on this page: there is nothing to open until you log in
st.markdown(
    """
    <style>
      [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] { display: none; }
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


# ---------- Header ----------
lottie("welcome.json", height=120, key="login_animation")
st.markdown(
    """
    <div class="om-auth-header">
      <div class="om-auth-title"><span class="om-gradient">OfficeMind</span></div>
      <p>Your private AI workplace assistant</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------- Card with two tabs ----------
with st.container(key="auth_card"):
    login_tab, signup_tab = st.tabs(["Log in", "Sign up"])

    with login_tab:
        with st.form("login_form"):
            username = st.text_input("Username", placeholder="e.g. priya.sharma")
            password = st.text_input("Password", type="password")
            log_in_clicked = st.form_submit_button(
                "Log in", type="primary", icon=":material/login:", width="stretch"
            )
        if log_in_clicked:
            with st.spinner("Checking..."):
                user = log_in(username, password)
            if user:
                start_session(user)
            else:
                st.error("Wrong username or password.", icon=":material/error:")

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
            new_password = st.text_input(
                "Password", type="password", help="At least 8 characters", key="signup_password"
            )
            confirm_password = st.text_input("Confirm password", type="password")
            sign_up_clicked = st.form_submit_button(
                "Create account", type="primary", icon=":material/person_add:", width="stretch"
            )
        if sign_up_clicked:
            if new_password != confirm_password:
                st.error("The two passwords don't match.", icon=":material/error:")
            else:
                with st.spinner("Creating your account..."):
                    user, error = sign_up(full_name, new_username, new_password)
                if error:
                    st.error(error, icon=":material/error:")
                else:
                    start_session(user)
