"""Screen protection: watermark, copy/print blocking, blur when the window isn't active,
idle sign-out in the browser, and the Secure mode (webcam phone check) panel.

What this can and can't do (be honest with users about it):
- It makes casual leaks harder and traceable: every screenshot or photo carries the
  viewer's name, email and time, and copying text or printing is blocked.
- It can't stop a determined person: a phone camera, a screen recorder, the browser's
  developer tools, or another computer can still capture what's on screen.
"""

import base64
import html
import io
import json
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import streamlit as st
import streamlit.components.v1 as components

from core.config import IDLE_TIMEOUT_MINUTES

COMPONENT_DIR = Path(__file__).resolve().parent.parent.parent / "components" / "phone_guard"


# ---------- Watermark ----------
def watermark_html(user: dict, dark: bool) -> str:
    """A faint, diagonal, repeating watermark with the viewer's name, email and the time."""
    who = user.get("email") or f"@{user['username']}"
    text = html.escape(f"{user['full_name']} · {who} · {datetime.now():%d %b %Y %H:%M}")
    colour = "rgba(255,255,255,0.07)" if dark else "rgba(16,24,40,0.075)"
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='520' height='280'>"
        f"<text x='260' y='140' fill='{colour}' font-family='Inter, Segoe UI, sans-serif' font-size='15' "
        "font-weight='600' text-anchor='middle' transform='rotate(-28 260 140)'>"
        f"{text}</text></svg>"
    )
    return (f'<div class="om-watermark" aria-hidden="true" '
            f"style=\"background-image:url(&quot;data:image/svg+xml;utf8,{quote(svg)}&quot;)\"></div>")


# ---------- Copy / print blocking, blur, idle sign-out ----------
SHIELD_SCRIPT = """
<script>
(function () {
  const P = window.parent, D = P.document;
  P.__omCfg = CONFIG;                       // updated on every page load
  if (P.__omShield) return;                 // the listeners are added only once
  P.__omShield = true;

  const typing = el => el && el.closest && el.closest('input, textarea, [contenteditable="true"]');
  const block = e => { if (!typing(e.target)) e.preventDefault(); };
  ['copy', 'cut', 'contextmenu', 'dragstart', 'selectstart'].forEach(t => D.addEventListener(t, block, true));

  D.addEventListener('keydown', e => {
    const k = (e.key || '').toLowerCase(), mod = e.ctrlKey || e.metaKey;
    if (mod && (k === 'p' || k === 's')) e.preventDefault();                    // print, save page
    if (mod && ['c', 'x', 'a'].includes(k) && !typing(e.target)) e.preventDefault();
    if (k === 'printscreen') hide();
  }, true);
  D.addEventListener('keyup', e => {
    if (e.key === 'PrintScreen') { try { P.navigator.clipboard.writeText(''); } catch (_) {} }
  }, true);
  P.addEventListener('beforeprint', () => D.body.classList.add('om-printing'));
  P.addEventListener('afterprint', () => D.body.classList.remove('om-printing'));

  // Blur everything when OfficeMind isn't the active window
  function hide() { D.body.classList.add('om-blurred'); }
  function show() { D.body.classList.remove('om-blurred'); }
  P.addEventListener('blur', () => setTimeout(() => { if (!D.hasFocus()) hide(); }, 80));
  P.addEventListener('focus', show);
  D.addEventListener('visibilitychange', () => (D.hidden ? hide() : show()));
  D.addEventListener('pointerdown', show, true);

  // Sign out after the idle time, even if the tab is just left open
  let last = Date.now();
  ['mousemove', 'keydown', 'pointerdown', 'scroll', 'touchstart', 'wheel']
    .forEach(t => D.addEventListener(t, () => { last = Date.now(); }, { passive: true, capture: true }));
  setInterval(() => {
    const c = P.__omCfg;
    if (c && Date.now() - last > c.idleMinutes * 60000) {
      P.location.href = new URL(c.loginPath, P.location.origin + '/').href;
    }
  }, 15000);
})();
</script>
"""


def screen_shield() -> None:
    config = json.dumps({"idleMinutes": IDLE_TIMEOUT_MINUTES, "loginPath": "Login?reason=idle"})
    with st.container(key="om_shield"):  # hidden by style.css
        components.html(SHIELD_SCRIPT.replace("CONFIG", config), height=0)


# ---------- Secure mode (webcam phone check) ----------
_phone_guard = None


def _guard_component():
    global _phone_guard
    if _phone_guard is None:
        _phone_guard = components.declare_component("phone_guard", path=str(COMPONENT_DIR))
    return _phone_guard


def _decode(frame: str):
    from PIL import Image
    return Image.open(io.BytesIO(base64.b64decode(frame.split(",", 1)[1])))


def check_frame(user: dict, frame: str, state) -> tuple[bool, float]:
    """Check one webcam frame for a phone. On a detection, record it (at most once a
    minute) and alert the admin. `state` is st.session_state (or a dict in tests)."""
    from modules.security.activity import log_activity, raise_alert
    from modules.security.detector import phone_detected

    seen, confidence = phone_detected(_decode(frame))
    state["phone_seen"] = seen
    if seen and time.time() - state.get("last_phone_log", 0) > 60:
        state["last_phone_log"] = time.time()
        log_activity(user, "phone_detected", f"confidence {confidence:.0%}", "critical")
        raise_alert("phone_detected", user["username"],
                    f"A phone was pointed at {user['full_name']}'s screen while Secure mode was on "
                    f"(confidence {confidence:.0%}).", level="critical", dedupe_minutes=5)
    return seen, confidence


@st.fragment
def _guard(user: dict) -> None:
    """Runs on its own: each webcam frame reruns only this part of the page."""
    value = _guard_component()(interval=1500, phone=st.session_state.get("phone_seen", False),
                               key="phone_guard", default=None)
    state = st.session_state
    if not value:
        state.secure_active = False
        return
    if value.get("status") == "error":
        state.secure_active = False
        st.error("The camera couldn't start, so Confidential documents stay hidden. "
                 "Allow camera access in your browser, or turn Secure mode off.", icon=":material/videocam_off:")
        return
    state.secure_active = value.get("status") == "running"

    frame, number = value.get("frame"), value.get("n")
    if frame and number != state.get("last_frame_n"):  # each frame is checked once
        state.last_frame_n = number
        check_frame(user, frame, state)

    if state.get("phone_seen"):
        # Blur the page and show a warning until the phone is gone
        st.markdown(
            """<style>
            [data-testid="stMain"], .st-key-topbar { filter: blur(22px) !important; }
            .stApp::after {
              content: "Phone detected. Content is hidden while a phone is pointed at the screen. This has been recorded.";
              position: fixed; inset: 0; z-index: 1000040; display: grid; place-items: center;
              padding: 2rem; background: rgba(180, 35, 24, 0.22); color: #FFFFFF; font-weight: 700;
              font-size: 1.25rem; text-align: center; text-shadow: 0 1px 6px rgba(0,0,0,.6);
            }
            </style>""",
            unsafe_allow_html=True,
        )


def secure_mode_panel(user: dict) -> None:
    """Sidebar panel: consent, then the running webcam check (or a button to stop it)."""
    from modules.security.activity import log_activity
    from modules.security.detector import model_available

    with st.sidebar, st.container(key="panel_secure"):
        st.markdown('<div class="om-section">Secure mode</div>', unsafe_allow_html=True)
        if not model_available():
            st.caption("Secure mode needs models/yolov8n.onnx. Ask your admin to install it.")
            return

        if not st.session_state.get("secure_consent"):
            st.markdown(
                """<div class="om-consent"><strong>Confidential documents need Secure mode.</strong>
                Turning it on uses your <strong>webcam</strong> to check that no mobile phone is pointed
                at the screen.<ul>
                <li>Pictures are checked on this computer and <strong>never saved or sent</strong>.</li>
                <li>Only the event "phone detected" and the time go into the Activity Log.</li>
                <li>You can turn it off at any time. Without it, answers just leave out Confidential documents.</li>
                </ul></div>""",
                unsafe_allow_html=True,
            )
            if st.button("I agree, turn on Secure mode", icon=":material/videocam:", type="primary",
                         width="stretch", key="secure_on"):
                st.session_state.secure_consent = True
                log_activity(user, "secure_mode", "turned on (consent given)")
                st.rerun()
            return

        _guard(user)
        if st.button("Turn off Secure mode", icon=":material/videocam_off:", width="stretch", key="secure_off"):
            for key in ("secure_consent", "secure_active", "phone_seen"):
                st.session_state.pop(key, None)
            log_activity(user, "secure_mode", "turned off")
            st.rerun()
