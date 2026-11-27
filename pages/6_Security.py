"""Security page (admins only): alerts, activity log, users and security settings."""

import csv
import html
import io
from datetime import datetime

import streamlit as st

from core.auth import list_users, unlock_user, update_user
from core.config import (
    DEPARTMENTS,
    IDLE_TIMEOUT_MINUTES,
    LOCKOUT_ATTEMPTS,
    LOCKOUT_MINUTES,
    PASSWORD_MIN_LENGTH,
)
from core.ui import data_table, empty_state, heading, icon, page_setup, stat_cards
from modules.helpdesk.tickets import friendly_time
from modules.security.activity import (
    ACTIONS,
    count_recent,
    list_activity,
    list_alerts,
    log_activity,
    resolve_alert,
    secure_mode_enabled,
    set_setting,
    sql_time,
    utc_now,
)
from modules.security.detector import model_available
from modules.security.masking import mask

user = page_setup("pages/6_Security.py", "Security", "shield",
                  "Alerts, activity and access for the whole workspace.")

if user["role"] != "admin":
    empty_state("lock", "This page is for admins",
                "The security page shows everyone's activity, so only admins can open it.")
    st.stop()

if "security_message" in st.session_state:
    st.success(st.session_state.pop("security_message"), icon=":material/check_circle:")


def refresh(message: str) -> None:
    st.session_state.security_message = message
    st.rerun()


LEVEL_BADGE = {"info": "om-role-employee", "warning": "om-status-in_progress", "critical": "om-status-open"}


def action_badge(action: str, level: str) -> str:
    label, icon_name = ACTIONS.get(action, (action.replace("_", " ").title(), "info"))
    return f'<span class="om-status {LEVEL_BADGE.get(level, "")}">{icon(icon_name)}{html.escape(label)}</span>'


# ---------- Overview ----------
alerts = list_alerts()
stat_cards([
    {"icon": "notification_important", "label": "Open alerts", "value": len(alerts),
     "note": "need a look", "tone": "red" if alerts else "green"},
    {"icon": "password", "label": "Failed sign-ins", "value": count_recent("login_failed", 24 * 60),
     "note": "last 24 hours"},
    {"icon": "gpp_bad", "label": "Blocked prompt tricks", "value": count_recent("blocked_prompt", 7 * 24 * 60),
     "note": "last 7 days"},
    {"icon": "phone_android", "label": "Phone detections", "value": count_recent("phone_detected", 7 * 24 * 60),
     "note": "last 7 days", "tone": "red" if count_recent("phone_detected", 7 * 24 * 60) else "brand"},
])

alerts_tab, log_tab, users_tab, settings_tab = st.tabs([
    f":material/notification_important: Alerts ({len(alerts)})",
    ":material/history: Activity log",
    ":material/manage_accounts: Users",
    ":material/tune: Settings",
])

# ---------- Alerts ----------
with alerts_tab:
    show_resolved = st.toggle("Show resolved alerts", key="show_resolved")
    shown = list_alerts(include_resolved=show_resolved)
    if not shown:
        empty_state("verified_user", "No open alerts", "Suspicious activity will appear here.")
    for alert in shown:
        with st.container(key=f"panel_alert_{alert['id']}"):
            left, right = st.columns([5, 1], vertical_alignment="center")
            level_class = "om-status-open" if alert["level"] == "critical" else "om-status-in_progress"
            status = ('<span class="om-status om-status-closed">' + icon("check") + "Resolved</span>"
                      if alert["resolved"] else
                      f'<span class="om-status {level_class}">{icon("warning")}{alert["level"].title()}</span>')
            left.markdown(
                f"""<div class="om-ticket-top"><span class="om-ticket-title">{html.escape(mask(alert['message']))}</span>
                {status}</div>
                <div class="om-ticket-meta">{html.escape(alert['username'] or 'unknown')} ·
                {friendly_time(alert['created_at'])}</div>""",
                unsafe_allow_html=True,
            )
            if not alert["resolved"] and right.button("Resolve", key=f"resolve_{alert['id']}",
                                                      icon=":material/done:"):
                resolve_alert(user, alert["id"])
                refresh("Alert resolved.")

# ---------- Activity log ----------
with log_tab:
    periods = {"1": ("Last 24 hours", 1), "7": ("Last 7 days", 7), "30": ("Last 30 days", 30), "all": ("All time", None)}
    users = list_users()
    f1, f2, f3 = st.columns(3)
    period = f1.selectbox("Period", list(periods), index=1, format_func=lambda k: periods[k][0])
    who = f2.selectbox("Person", ["Everyone", *sorted({u["username"] for u in users})])
    what = f3.selectbox("Action", ["Everything", *ACTIONS], format_func=lambda a: ACTIONS[a][0] if a in ACTIONS else a)
    rows = list_activity(periods[period][1], None if who == "Everyone" else who,
                         None if what == "Everything" else what)
    if not rows:
        empty_state("history", "No activity for these filters")
    else:
        st.caption(f"{len(rows)} event{'s' if len(rows) != 1 else ''} (newest first). "
                   "Personal data in the details is masked.")
        data_table(
            ["Time", "Person", "Action", "Details"],
            [[friendly_time(r["created_at"]), html.escape(r["username"] or "unknown"),
              action_badge(r["action"], r["level"]), html.escape(mask(r["details"])[:200])] for r in rows],
        )

        def export_log() -> bytes:
            log_activity(user, "export", f"Activity log CSV · {periods[period][0]}")
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(["Time (UTC)", "Person", "Action", "Level", "Details"])
            for r in rows:
                writer.writerow([r["created_at"], r["username"], ACTIONS.get(r["action"], (r["action"],))[0],
                                 r["level"], mask(r["details"])])
            return buffer.getvalue().encode("utf-8")

        st.download_button("Export activity log (CSV)", data=export_log, on_click="ignore",
                           file_name=f"officemind-activity-{datetime.now():%Y-%m-%d}.csv", mime="text/csv",
                           icon=":material/download:")

# ---------- Users ----------
with users_tab:
    now = sql_time(utc_now())
    heading("Everyone")
    data_table(
        ["Name", "Username", "Role", "Department", "Confidential access", "Status"],
        [[f"<strong>{html.escape(u['full_name'])}</strong>", "@" + html.escape(u["username"]),
          f'<span class="om-role om-role-{u["role"]}">{u["role"].title()}</span>',
          html.escape(u["department"]),
          "Always (admin)" if u["role"] == "admin" else ("Yes" if u["clearance"] else "No"),
          (f'<span class="om-status om-status-open">{icon("lock")}Locked</span>'
           if u["locked_until"] and u["locked_until"] > now
           else f'<span class="om-status om-status-closed">{icon("check")}Active</span>')]
         for u in users],
    )
    heading("Change a person")
    chosen = st.selectbox("Person", users, format_func=lambda u: f"{u['full_name']} (@{u['username']})",
                          key="edit_user")
    with st.form("edit_user_form"):
        department = st.selectbox("Department", DEPARTMENTS,
                                  index=DEPARTMENTS.index(chosen["department"]) if chosen["department"] in DEPARTMENTS else 0)
        email = st.text_input("Email", value=chosen["email"] or "")
        clearance = st.toggle("Confidential access", value=bool(chosen["clearance"]),
                              disabled=chosen["role"] == "admin",
                              help="Lets this person get answers from Confidential documents.")
        if st.form_submit_button("Save changes", type="primary", icon=":material/save:"):
            error = update_user(user, chosen["id"], department, clearance, email)
            if error:
                st.error(error, icon=":material/error:")
            else:
                refresh(f"Saved changes for {chosen['full_name']}.")
    if chosen["locked_until"] and chosen["locked_until"] > now:
        if st.button(f"Unlock {chosen['full_name']}'s account", icon=":material/lock_open:"):
            unlock_user(user, chosen["id"])
            refresh(f"{chosen['full_name']} can sign in again.")

# ---------- Settings ----------
with settings_tab:
    heading("Secure mode")
    st.markdown(
        '<p class="om-muted">When on, people who may see Confidential documents only get answers from them '
        "while their webcam check is running (after they agree). A phone pointed at the screen hides the "
        "content and is recorded here.</p>",
        unsafe_allow_html=True,
    )
    if not model_available():
        st.warning("The YOLO model (models/yolov8n.onnx) is missing, so Secure mode can't run.",
                   icon=":material/warning:")
    enabled = st.toggle("Use Secure mode for Confidential documents", value=secure_mode_enabled(),
                        disabled=not model_available())
    if enabled != secure_mode_enabled():
        set_setting(user, "secure_mode_enabled", "1" if enabled else "0")
        refresh(f"Secure mode {'on' if enabled else 'off'}.")

    heading("Policies in place")
    data_table(["Protection", "Setting"], [
        ["Strong passwords", f"{PASSWORD_MIN_LENGTH}+ characters with a letter, number and symbol"],
        ["Account lockout", f"{LOCKOUT_MINUTES} minutes after {LOCKOUT_ATTEMPTS} wrong passwords"],
        ["Automatic sign-out", f"after {IDLE_TIMEOUT_MINUTES} minutes without activity"],
        ["Encryption at rest", "Ticket text, replies, AI questions, activity details, alerts and emails"],
        ["Masking in answers", "Phone numbers, emails, Aadhaar, PAN and bank account numbers → ****"],
        ["Screen protection", "Watermark, no copy/print/right-click, blur when the window isn't active"],
    ])
    st.caption("These values live in core/config.py. Keep a safe backup of data/secret.key: "
               "without it, encrypted data can't be read.")
