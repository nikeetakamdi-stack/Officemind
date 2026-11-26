"""OfficeMind home page. Run with:  streamlit run app.py"""

import streamlit as st

st.set_page_config(page_title="OfficeMind", page_icon="🧠")

st.title("🧠 OfficeMind")
st.write("Your AI workplace assistant. Everything runs on your own computer.")

st.subheader("Modules")
st.page_link("pages/1_Knowledge_Assistant.py", label="Knowledge Assistant", icon="📚")
st.caption("Coming soon: Helpdesk · Onboarding · Dashboard")
