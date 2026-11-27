"""Manager dashboard (admins only): tickets, onboarding and AI questions at a glance."""

import html
from datetime import datetime

import plotly.graph_objects as go
import streamlit as st

from core.ui import apply_style, is_admin, require_login, sidebar_menu
from modules.dashboard.metrics import (
    RANGES,
    document_count,
    employees_onboarding,
    excel_report,
    format_duration,
    onboarding_now,
    question_count,
    ticket_stats,
    tickets_by_category,
    tickets_by_urgency,
    tickets_over_time,
    top_questions,
    unanswered_questions,
)
from modules.helpdesk.tickets import URGENCIES
from modules.onboarding.checklists import STATUSES as ONBOARDING_STATUSES

st.set_page_config(page_title="Dashboard · OfficeMind", page_icon="📊", layout="wide")
apply_style()
user = require_login()  # not logged in? -> login page
sidebar_menu()

st.markdown(
    """
    <div class="om-page-title">📊 <span class="om-gradient">Dashboard</span></div>
    <p class="om-page-subtitle">Tickets, onboarding and AI questions at a glance.</p>
    """,
    unsafe_allow_html=True,
)

# Employees can't see this page (the sidebar link is hidden too)
if not is_admin():
    st.markdown(
        '<div class="om-empty-state">🔒 The dashboard is only for admins.</div>',
        unsafe_allow_html=True,
    )
    st.stop()


# ---------- Chart style ----------
# Colours checked with a colour-blindness validator against the dark card background.
ACCENT = "#8B74FF"  # one colour for single-measure charts
URGENCY_COLORS = {"high": "#E8364F", "medium": "#C98500", "low": "#3987E5"}
TEXT = "#E5E7EB"
MUTED = "#9CA3AF"
GRID = "rgba(255,255,255,0.06)"
AXIS = "rgba(255,255,255,0.14)"
CHART_CONFIG = {"displayModeBar": False, "responsive": True}


def style(fig: go.Figure, height: int = 280) -> go.Figure:
    """Same look for every chart: transparent background, quiet grid, readable tooltips."""
    fig.update_layout(
        height=height,
        margin=dict(l=4, r=12, t=8, b=4),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, sans-serif", size=12, color=MUTED),
        showlegend=False,
        barcornerradius=4,  # rounded bar ends
        hoverlabel=dict(bgcolor="#182136", bordercolor="rgba(255,255,255,0.15)",
                        font=dict(color=TEXT, family="Inter, sans-serif")),
        transition=dict(duration=500, easing="cubic-in-out"),  # smooth updates when the filter changes
    )
    fig.update_xaxes(showgrid=False, linecolor=AXIS, ticks="", tickfont=dict(color=MUTED))
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor=AXIS, tickfont=dict(color=MUTED))
    return fig


def chart_card(key: str, title: str, subtitle: str = ""):
    """A rounded card with a title; the chart goes inside (use it with `with`)."""
    box = st.container(key=f"chart_{key}")
    box.markdown(
        f'<div class="om-chart-title">{title}</div>'
        + (f'<div class="om-chart-sub">{subtitle}</div>' if subtitle else ""),
        unsafe_allow_html=True,
    )
    return box


def no_data(text: str = "No data for this period yet.") -> None:
    st.markdown(f'<div class="om-chart-empty">{text}</div>', unsafe_allow_html=True)


# ---------- Filter + export (one row, above everything) ----------
filter_column, export_column = st.columns([3, 1], vertical_alignment="center")
with filter_column:
    choice = st.segmented_control(
        "Period", list(RANGES), default="30",
        format_func=lambda key: RANGES[key][0], label_visibility="collapsed",
    ) or "30"
range_label, days = RANGES[choice]
with export_column:
    st.download_button(
        "Export to Excel",
        data=excel_report(user, days, range_label),
        file_name=f"officemind-dashboard-{choice}-{datetime.now():%Y-%m-%d}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        icon=":material/download:",
        type="primary",
        width="stretch",
        on_click="ignore",  # downloading doesn't reload the page
    )

# ---------- Stat cards ----------
stats = ticket_stats(days)
onboarding = onboarding_now(user)
asked, answered = question_count(days)
cards = [
    ("🎫", stats["total"], "Total tickets", range_label.lower()),
    ("🟠", stats["open"], "Open tickets", "not closed yet"),
    ("⏱️", format_duration(stats["avg_close_hours"]), "Avg. time to close",
     f"{stats['closed']} closed" if stats["closed"] else "no tickets closed"),
    ("📄", document_count(), "Documents", "in the knowledge base"),
    ("🚀", employees_onboarding(onboarding), "Onboarding", "employees in progress"),
]
st.markdown(
    '<div class="om-kpis">'
    + "".join(
        f"""<div class="om-kpi" style="--i:{i}">
              <div class="om-kpi-icon">{icon}</div>
              <div class="om-kpi-value">{value}</div>
              <div class="om-kpi-label">{label}</div>
              <div class="om-kpi-note">{note}</div>
            </div>"""
        for i, (icon, value, label, note) in enumerate(cards)
    )
    + "</div>",
    unsafe_allow_html=True,
)

# ---------- Tickets over time (full width) ----------
points, unit = tickets_over_time(days)
with chart_card("over_time", "Tickets over time", f"New tickets per {unit} · {range_label.lower()}"):
    if not any(count for _, count in points):
        no_data()
    else:
        dates = [day for day, _ in points]
        counts = [count for _, count in points]
        label = "Week of %d %b" if unit == "week" else "%a %d %b"
        fig = go.Figure(
            go.Scatter(
                x=dates, y=counts, mode="lines+markers",
                line=dict(color=ACCENT, width=2),  # straight lines: a curve would invent in-between values
                marker=dict(size=8, color=ACCENT, line=dict(color="#131A2A", width=2)),
                fill="tozeroy", fillcolor="rgba(139,116,255,0.12)",
                hovertemplate=f"%{{x|{label}}}<br><b>%{{y}}</b> new tickets<extra></extra>",
            )
        )
        style(fig, height=260).update_layout(hovermode="x")
        fig.update_xaxes(showspikes=True, spikemode="across", spikethickness=1,
                         spikecolor=AXIS, spikedash="solid")
        fig.update_yaxes(rangemode="tozero", dtick=max(1, round(max(counts) / 4)))
        st.plotly_chart(fig, config=CHART_CONFIG, key="plot_time")

# ---------- Category + urgency (side by side) ----------
left, right = st.columns(2)
with left:
    categories = tickets_by_category(days)
    with chart_card("category", "Tickets by category", range_label):
        if not any(count for _, count in categories):
            no_data()
        else:
            fig = go.Figure(
                go.Bar(
                    x=[c for c, _ in categories], y=[n for _, n in categories],
                    marker=dict(color=ACCENT), width=0.55,
                    text=[n or "" for _, n in categories], textposition="outside",
                    textfont=dict(color=TEXT), cliponaxis=False,
                    hovertemplate="%{x}<br><b>%{y}</b> tickets<extra></extra>",
                )
            )
            style(fig).update_yaxes(rangemode="tozero", showticklabels=False, showgrid=False)
            st.plotly_chart(fig, config=CHART_CONFIG, key="plot_category")

with right:
    urgencies = tickets_by_urgency(days)
    with chart_card("urgency", "Tickets by urgency", range_label):
        if not any(count for _, count in urgencies):
            no_data()
        else:
            ordered = list(reversed(urgencies))  # High at the top of a horizontal chart
            fig = go.Figure(
                go.Bar(
                    y=[URGENCIES[k] for k, _ in ordered], x=[n for _, n in ordered],
                    orientation="h", width=0.55,
                    marker=dict(color=[URGENCY_COLORS[k] for k, _ in ordered]),
                    text=[n or "" for _, n in ordered], textposition="outside",
                    textfont=dict(color=TEXT), cliponaxis=False,
                    hovertemplate="%{y} urgency<br><b>%{x}</b> tickets<extra></extra>",
                )
            )
            style(fig).update_xaxes(rangemode="tozero", showticklabels=False)
            fig.update_yaxes(showgrid=False, tickfont=dict(color=TEXT))
            st.plotly_chart(fig, config=CHART_CONFIG, key="plot_urgency")

# ---------- Onboarding progress ----------
STATUS_ICONS = {"completed": "🟢", "on_track": "🔵", "not_started": "⚪", "stuck": "🔴"}
with chart_card("onboarding", "Onboarding progress", "Every new employee, right now"):
    if not onboarding:
        no_data("Nobody is onboarding yet.")
    else:
        rows = list(reversed(onboarding))  # first name at the top
        names = [f"{r['employee']} · {r['checklist']}" for r in rows]
        fig = go.Figure(
            go.Bar(
                y=names, x=[r["percent"] for r in rows], orientation="h", width=0.5,
                marker=dict(color=ACCENT),
                text=[f"{r['done']}/{r['total']} · {STATUS_ICONS[r['status']]} {ONBOARDING_STATUSES[r['status']]}"
                      for r in rows],
                textposition="outside", textfont=dict(color=TEXT), cliponaxis=False,
                customdata=[[r["days_idle"]] for r in rows],
                hovertemplate="%{y}<br><b>%{x}%</b> done · last activity %{customdata[0]} days ago<extra></extra>",
            )
        )
        style(fig, height=max(160, 46 * len(rows) + 40))
        fig.update_xaxes(range=[0, 135], showticklabels=False)  # room for the labels
        fig.update_yaxes(showgrid=False, tickfont=dict(color=TEXT), automargin=True)
        st.plotly_chart(fig, config=CHART_CONFIG, key="plot_onboarding")

# ---------- AI questions ----------
left, right = st.columns(2)
with left:
    top = top_questions(days)
    with chart_card("questions", "Most-asked questions",
                    f"{asked} asked · {answered} answered from documents"):
        if not top:
            no_data("No questions asked in this period.")
        else:
            rows = list(reversed(top))
            short = [q["question"] if len(q["question"]) <= 42 else q["question"][:40] + "…" for q in rows]
            fig = go.Figure(
                go.Bar(
                    y=short, x=[q["times"] for q in rows], orientation="h", width=0.55,
                    marker=dict(color=ACCENT),
                    text=[q["times"] for q in rows], textposition="outside",
                    textfont=dict(color=TEXT), cliponaxis=False,
                    customdata=[[q["question"], "yes" if q["answered"] else "no"] for q in rows],
                    hovertemplate="%{customdata[0]}<br><b>%{x}</b>× asked · answered: %{customdata[1]}<extra></extra>",
                )
            )
            style(fig, height=max(180, 38 * len(rows) + 40))
            fig.update_xaxes(showticklabels=False, rangemode="tozero")
            fig.update_yaxes(showgrid=False, tickfont=dict(color=TEXT), automargin=True)
            st.plotly_chart(fig, config=CHART_CONFIG, key="plot_questions")

with right:
    missing = unanswered_questions(days)
    with chart_card("unanswered", "Unanswered questions",
                    "The AI couldn't answer these from the documents: consider adding a document"):
        if not missing:
            no_data("🎉 Every question was answered from the documents.")
        else:
            items = "".join(
                f"""<li style="--i:{i}"><span class="om-q-text">{html.escape(q['question'])}</span>
                    <span class="om-q-count">{q['times']}×</span></li>"""
                for i, q in enumerate(missing)
            )
            st.markdown(f'<ul class="om-q-list">{items}</ul>', unsafe_allow_html=True)
