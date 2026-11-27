"""Shared look & feel for every OfficeMind page.

Every page starts with page_setup(), which applies the theme, checks the login and
draws the top bar, the sidebar and the page title. The rest of this file holds the
building blocks all pages share (badges, stat cards, tables, empty states, errors,
skeleton loaders), so every page looks and behaves the same.
"""

import html
import re
import time
from pathlib import Path

import streamlit as st

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
LOGO_PNG = str(ASSETS_DIR / "logo.png")
LOGIN_PAGE = "pages/0_Login.py"
SEARCH_PAGE = "pages/5_Search.py"

# OfficeMind's logo: deep-blue tile, white "O" (Office) and a light-blue spark (Mind)
LOGO_SVG = """<svg width="{size}" height="{size}" viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
<defs><linearGradient id="om-logo-g" x1="0" y1="0" x2="0" y2="1">
<stop offset="0" stop-color="#2D63D8"/><stop offset="1" stop-color="#173E96"/></linearGradient></defs>
<rect width="32" height="32" rx="8" fill="url(#om-logo-g)"/>
<circle cx="15" cy="17" r="7.2" fill="none" stroke="#fff" stroke-width="3"/>
<circle cx="23.2" cy="8.8" r="2.6" fill="#7FB2FF"/></svg>"""

# (page file, label, icon, admin only)
NAV = [
    ("app.py", "Home", "home", False),
    ("pages/1_Knowledge_Assistant.py", "Knowledge Assistant", "menu_book", False),
    ("pages/2_Helpdesk.py", "Helpdesk", "support_agent", False),
    ("pages/3_Onboarding.py", "Onboarding", "task_alt", False),
    ("pages/7_Team_Chat.py", "Team Chat", "forum", False),
    ("pages/8_Code_Review.py", "Code Review", "code", False),
    ("pages/4_Dashboard.py", "Dashboard", "monitoring", True),
    ("pages/6_Security.py", "Security", "shield", True),
]


# ---------- Who is logged in ----------
def current_user() -> dict | None:
    """The logged-in user (id, username, full_name, role), or None."""
    return st.session_state.get("user")


def require_login() -> dict:
    """Send visitors who are not signed in to the sign-in page, and sign people out
    after IDLE_TIMEOUT_MINUTES without any activity."""
    from core.auth import refresh_user
    from core.config import IDLE_TIMEOUT_MINUTES
    from modules.security.activity import log_activity

    user = current_user()
    if user is None:
        st.switch_page(LOGIN_PAGE)  # stops this page here

    now = time.time()
    last_active = st.session_state.get("last_active", now)
    if now - last_active > IDLE_TIMEOUT_MINUTES * 60:
        log_activity(user, "auto_logout", f"no activity for {IDLE_TIMEOUT_MINUTES} minutes")
        st.session_state.clear()
        st.switch_page(LOGIN_PAGE, query_params={"reason": "idle"})
    st.session_state.last_active = now

    # Read the account again, so changes by an admin (department, access) apply at once
    user = refresh_user(user)
    st.session_state.user = user
    return user


def is_admin() -> bool:
    user = current_user()
    return user is not None and user["role"] == "admin"


def log_out() -> None:
    """Forget the user, their chats and settings, then go back to the login page."""
    from modules.security.activity import log_activity
    log_activity(current_user(), "logout")
    st.session_state.clear()
    st.switch_page(LOGIN_PAGE)


# ---------- Theme ----------
def is_dark() -> bool:
    return st.session_state.get("theme") == "dark"


def _toggle_theme() -> None:
    st.session_state.theme = "dark" if st.session_state.get("dark_toggle") else "light"


def apply_style() -> None:
    """Load the design system (style.css), plus dark.css when dark mode is on."""
    css = (ASSETS_DIR / "style.css").read_text(encoding="utf-8")
    if is_dark():
        css += (ASSETS_DIR / "dark.css").read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def chart_theme() -> dict:
    """Colours for Plotly charts, matching the current theme.
    All colours were checked with a colour-blindness validator on that theme's card colour."""
    if is_dark():
        return {
            "accent": "#5B8DEF", "fill": "rgba(91,141,239,0.14)", "text": "#E6E9EE",
            "muted": "#8F99A6", "grid": "rgba(255,255,255,0.06)", "axis": "#3B4350",
            "ring": "#191D23", "hover_bg": "#1F242B", "hover_border": "#3B4350",
            "urgency": {"high": "#E8364F", "medium": "#C98500", "low": "#3987E5"},
        }
    return {
        "accent": "#1F4FB5", "fill": "rgba(31,79,181,0.10)", "text": "#1A1D23",
        "muted": "#6B7584", "grid": "rgba(16,24,40,0.07)", "axis": "#CDD4DD",
        "ring": "#FFFFFF", "hover_bg": "#FFFFFF", "hover_border": "#E3E7ED",
        "urgency": {"high": "#D92D20", "medium": "#C48200", "low": "#2A78D6"},
    }


# ---------- Small HTML helpers ----------
def icon(name: str, size: int | None = None) -> str:
    """A Material Symbols icon, e.g. icon("home")."""
    style = f' style="font-size:{size}px"' if size else ""
    return f'<span class="msr"{style}>{name}</span>'


def brand_html(size: int = 30, tag: bool = True) -> str:
    badge = '<span class="om-brand-tag">AI</span>' if tag else ""
    return (
        f'<div class="om-brand">{LOGO_SVG.format(size=size)}'
        f'<span class="om-brand-name">OfficeMind</span>{badge}</div>'
    )


def initials(name: str) -> str:
    parts = [p for p in name.split() if p]
    return html.escape(("".join(p[0] for p in parts[:2]) or "?").upper())


# ---------- The shell: top bar, sidebar, page title ----------
def page_setup(page: str, title: str, icon_name: str, subtitle: str = "", header: bool = True) -> dict:
    """Start every page with this. Returns the logged-in user."""
    st.set_page_config(page_title=f"{title} · OfficeMind", page_icon=LOGO_PNG, layout="wide",
                       initial_sidebar_state="expanded")
    apply_style()
    user = require_login()  # not logged in? -> login page
    from modules.chat.store import touch_presence
    touch_presence(user)  # shows this person as "online" in Team Chat
    _screen_protection(user)
    top_bar(user)
    sidebar_menu(user, page)
    if header:
        page_header(title, icon_name, subtitle)
    return user


def _screen_protection(user: dict) -> None:
    """Watermark, copy/print blocking, blur when inactive, and Secure mode (if it applies)."""
    from modules.security.access import can_see_confidential
    from modules.security.activity import secure_mode_enabled
    from modules.security.screen import screen_shield, secure_mode_panel, watermark_html

    st.markdown(watermark_html(user, is_dark()), unsafe_allow_html=True)
    screen_shield()
    if secure_mode_enabled() and can_see_confidential(user):
        secure_mode_panel(user)


def top_bar(user: dict) -> None:
    """Logo, search box, notification bell and profile menu, fixed at the top."""
    from modules.notifications import notifications_for  # imported here to avoid a loop

    with st.container(key="topbar"):
        logo, search, bell, profile = st.columns([2.2, 5, 0.75, 1.6], vertical_alignment="center")
        logo.markdown(brand_html(), unsafe_allow_html=True)

        with search:
            with st.form("global_search", border=False, enter_to_submit=True):
                query = st.text_input(
                    "Search", placeholder="Search tickets, documents, tasks…",
                    label_visibility="collapsed", icon=":material/search:",
                )
                submitted = st.form_submit_button("Search")
            if submitted and query.strip():
                st.switch_page(SEARCH_PAGE, query_params={"q": query.strip()})

        items = notifications_for(user)
        with bell:
            with st.popover(str(len(items)) if items else " ", icon=":material/notifications:",
                            key="notif_menu", help="Notifications"):
                st.markdown('<div class="om-menu-title">Notifications</div>', unsafe_allow_html=True)
                if not items:
                    st.markdown('<div class="om-notif-empty">You\'re all caught up.</div>',
                                unsafe_allow_html=True)
                for item in items:
                    st.page_link(item["page"], label=item["text"], icon=f":material/{item['icon']}:")

        with profile:
            first_name = user["full_name"].split()[0]
            with st.popover(first_name, key="profile_menu", icon=":material/account_circle:"):
                st.markdown(
                    f"""
                    <div class="om-menu-head">
                      <span class="om-avatar">{initials(user['full_name'])}</span>
                      <div><div class="om-menu-title">{html.escape(user['full_name'])}</div>
                      <div class="om-menu-sub">@{html.escape(user['username'])} ·
                      <span class="om-role om-role-{user['role']}">{user['role'].title()}</span></div></div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                st.divider()
                st.toggle("Dark mode", value=is_dark(), key="dark_toggle", on_change=_toggle_theme)
                with st.expander("Change password", icon=":material/key:"):
                    _change_password_form(user)
                if st.button("Log out", icon=":material/logout:", key="logout", width="stretch"):
                    log_out()


def _change_password_form(user: dict) -> None:
    from core.auth import PASSWORD_RULES, change_password
    with st.form("change_password", clear_on_submit=True, border=False):
        old = st.text_input("Current password", type="password")
        new = st.text_input("New password", type="password", help=PASSWORD_RULES)
        again = st.text_input("Repeat new password", type="password")
        if st.form_submit_button("Update password", type="primary", width="stretch"):
            if new != again:
                st.error("The new passwords don't match.", icon=":material/error:")
            else:
                error = change_password(user, old, new)
                if error:
                    st.error(error, icon=":material/error:")
                else:
                    st.success("Password updated.", icon=":material/check_circle:")


def sidebar_menu(user: dict, current: str) -> None:
    """The collapsible sidebar with an icon for each page. The current page is highlighted."""
    with st.sidebar:
        st.markdown('<div class="om-nav-label">Workspace</div>', unsafe_allow_html=True)
        admin_label_shown = False
        for page, label, icon_name, admin_only in NAV:
            if admin_only:
                if user["role"] != "admin":
                    continue
                if not admin_label_shown:
                    st.markdown('<div class="om-nav-label">Admin</div>', unsafe_allow_html=True)
                    admin_label_shown = True
            # The container's name says whether this is the current page; style.css highlights it
            active = "active" if page == current else ""
            if page == "pages/7_Team_Chat.py":
                from modules.chat.store import unread_total
                unread = unread_total(user)
                label = f"{label}  ({unread})" if unread else label  # unread messages badge
            with st.container(key=f"nav{active}_{icon_name}"):
                st.page_link(page, label=label, icon=f":material/{icon_name}:")
        st.markdown('<div class="om-nav-end"></div>', unsafe_allow_html=True)


def page_header(title: str, icon_name: str, subtitle: str = "") -> None:
    sub = f'<p class="om-page-subtitle">{html.escape(subtitle)}</p>' if subtitle else ""
    st.markdown(
        f"""
        <div class="om-page-head">
          <div class="om-page-icon">{icon(icon_name)}</div>
          <div><div class="om-page-title" role="heading" aria-level="1">{html.escape(title)}</div>{sub}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_title(text: str) -> None:
    """Small grey uppercase title, used to split the sidebar into sections."""
    st.markdown(f'<div class="om-section">{html.escape(text)}</div>', unsafe_allow_html=True)


def heading(text: str) -> None:
    """A section heading inside a page."""
    st.markdown(f'<div class="om-h2">{html.escape(text)}</div>', unsafe_allow_html=True)


# ---------- Empty states, friendly errors, skeletons ----------
def empty_state(icon_name: str, title: str, text: str = "") -> None:
    body = f'<div class="om-empty-text">{text}</div>' if text else ""
    st.markdown(
        f"""<div class="om-empty"><div class="om-icon-tile">{icon(icon_name)}</div>
        <div class="om-empty-title">{html.escape(title)}</div>{body}</div>""",
        unsafe_allow_html=True,
    )


def friendly_error(title: str, text: str, details: str | None = None) -> None:
    """A calm error card with a plain-language explanation (technical details folded away)."""
    st.markdown(
        f"""<div class="om-error">{icon("error")}<div>
        <div class="om-error-title">{html.escape(title)}</div>
        <div class="om-error-text">{text}</div></div></div>""",
        unsafe_allow_html=True,
    )
    if details:
        with st.expander("Technical details"):
            st.code(details, language=None)


AI_OFFLINE = (
    "The AI assistant isn't reachable right now",
    "Make sure Ollama is running on this computer, then try again.",
)


def skeleton_html(lines: int = 3, title: bool = True, label: str = "", height: int | None = None) -> str:
    """Grey shimmering placeholders, shown while something is loading."""
    if height:
        body = f'<div class="om-skel om-skel-block" style="min-height:{height}px"></div>'
    else:
        widths = [92, 78, 85, 60, 70]
        body = "".join(
            f'<div class="om-skel om-skel-line" style="width:{widths[i % len(widths)]}%"></div>'
            for i in range(lines)
        )
    head = '<div class="om-skel om-skel-title"></div>' if title else ""
    note = f'<div class="om-skel-label">{html.escape(label)}</div>' if label else ""
    return f'<div class="om-skel-card">{head}{body}{note}</div>'


def thinking_html(text: str) -> str:
    """Skeleton lines with a short message, shown while the AI is working."""
    lines = "".join(
        f'<div class="om-skel om-skel-line" style="width:{w}%"></div>' for w in (90, 72, 50)
    )
    return f'<div class="om-thinking">{lines}<div class="om-skel-label">{html.escape(text)}</div></div>'


THINKING_HTML = thinking_html("Searching your documents…")


def typing_effect(text: str, delay: float = 0.02):
    """Give back the text a word at a time, so st.write_stream "types" it out."""
    for piece in re.split(r"(\s+)", text):  # keep spaces and line breaks
        yield piece
        if piece.strip():
            time.sleep(delay)


# ---------- Stat cards and tables ----------
def stat_cards(cards: list[dict]) -> None:
    """cards: [{"icon", "label", "value", "note", "tone" (optional: red/amber/green)}]"""
    st.markdown(
        '<div class="om-kpis">'
        + "".join(
            f"""<div class="om-kpi om-kpi-{c.get('tone', 'brand')}">
                  <div class="om-icon-tile">{icon(c['icon'])}</div>
                  <div><div class="om-kpi-label">{html.escape(c['label'])}</div>
                  <div class="om-kpi-value">{html.escape(str(c['value']))}</div>
                  <div class="om-kpi-note">{html.escape(c.get('note', ''))}</div></div>
                </div>"""
            for c in cards
        )
        + "</div>",
        unsafe_allow_html=True,
    )


def data_table(columns: list[str], rows: list[list[str]]) -> None:
    """A clean table. Cells are HTML, so escape any text with html.escape first."""
    head = "".join(f"<th>{html.escape(c)}</th>" for c in columns)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    st.markdown(
        f'<div class="om-table-wrap"><table class="om-table"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>",
        unsafe_allow_html=True,
    )


def progress_cell(percent: int) -> str:
    return (
        f'<div class="om-cell-progress"><div class="om-progress">'
        f'<div class="om-progress-fill" style="--from:0%;--to:{percent}%"></div></div>'
        f"<span>{percent}%</span></div>"
    )


# ---------- Badges ----------
STATUS_ICONS = {"open": "radio_button_unchecked", "in_progress": "progress_activity", "closed": "check_circle"}
URGENCY_ICONS = {"high": "keyboard_double_arrow_up", "medium": "drag_handle", "low": "keyboard_arrow_down"}
ONBOARDING_ICONS = {"completed": "check_circle", "on_track": "trending_up",
                    "not_started": "schedule", "stuck": "error"}


def status_badge(status: str, label: str) -> str:
    """Ticket status pill: red Open, amber In Progress, green Closed (always with icon + word)."""
    return (f'<span class="om-status om-status-{status}">{icon(STATUS_ICONS.get(status, "circle"))}'
            f"{html.escape(label)}</span>")


def urgency_tag(urgency: str, label: str, title: str = "") -> str:
    """Urgency tag: High, Medium or Low. `title` shows when you hover over it."""
    hover = f' title="{html.escape(title)}"' if title else ""
    return (f'<span class="om-urgency om-urgency-{urgency}"{hover}>'
            f'{icon(URGENCY_ICONS.get(urgency, "drag_handle"))}{html.escape(label)}</span>')


def onboarding_badge(status: str, label: str) -> str:
    return (f'<span class="om-status om-ob-{status}">{icon(ONBOARDING_ICONS[status])}'
            f"{html.escape(label)}</span>")


def sources_html(sources: list[dict]) -> str:
    """Turn [{"source": file, "page": n}, ...] into small chips."""
    chips = "".join(
        f'<span class="om-chip">{icon("description")}{html.escape(s["source"])} · page {s["page"]}</span>'
        for s in sources
    )
    return f'<div class="om-sources">{chips}</div>'
