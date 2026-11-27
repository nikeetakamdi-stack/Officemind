"""Secure mode: webcam phone detection while Confidential documents may be on screen.

Rules:
- An admin decides whether Secure mode is used at all (Security page → Settings).
- When it's on, people who may see Confidential documents only get answers from
  them after they agree to Secure mode and the webcam is running.
- Nothing from the webcam is saved: frames are checked in memory, and only the
  event "phone detected" (with the time) goes into the Activity Log.
"""

import streamlit as st

from modules.security.access import can_see_confidential
from modules.security.activity import secure_mode_enabled


def secure_active() -> bool:
    """True while this person's Secure mode (webcam check) is running."""
    return bool(st.session_state.get("secure_active"))


def confidential_allowed(user: dict) -> bool:
    """May Confidential documents be used right now for this user?"""
    if not can_see_confidential(user):
        return False
    if secure_mode_enabled():
        return secure_active()
    return True
