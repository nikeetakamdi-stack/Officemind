"""Manager dashboard (admins only): tickets, onboarding and AI questions at a glance."""

import html
from datetime import datetime

import plotly.graph_objects as go
import streamlit as st

from core.ui import chart_theme, empty_state, icon, onboarding_badge, page_setup, skeleton_html, stat_cards
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

user = page_setup("pages/4_Dashboard.py", "Dashboard", "monitoring",
                  "Tickets, onboarding and AI questions at a glance.")

# Employees can't see this page (the sidebar link is hidden too)
if user["role"] != "admin":
    empty_state("lock", "This page is for admins",
                "The dashboard shows company-wide numbers, so only admins can open it.")
    st.stop()


# ---------- Chart style (colours follow the light/dark theme) ----------
T = chart_theme()
CHART_CONFIG = {"displayModeBar": False, "responsive": True}


def style(fig: go.Figure, height: int = 280) -> go.Figure:
    """Same look for every chart: transparent background, quiet grid, readable tooltips."""
    fig.update_layout(
        height=height,
        margin=dict(l=4, r=12, t=8, b=4),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, Segoe UI, sans-serif", size=12, color=T["muted"]),
        showlegend=False,
        barcornerradius=4,  # rounded bar ends
        hoverlabel=dict(bgcolor=T["hover_bg"], bordercolor=T["hover_border"],
                        font=dict(color=T["text"], family="Inter, Segoe UI, sans-serif")),
        transition=dict(duration=400, easing="cubic-in-out"),  # smooth updates when the filter changes
    )
    fig.update_xaxes(showgrid=False, linecolor=T["axis"], ticks="", tickfont=dict(color=T["muted"]))
    fig.update_yaxes(gridcolor=T["grid"], zeroline=False, linecolor=T["axis"], tickfont=dict(color=T["muted"]))
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
    st.markdown(f'<div class="om-chart-empty">{icon("bar_chart", 28)}<br>{text}</div>',
                unsafe_allow_html=True)


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
        data=lambda: excel_report(user, days, range_label),  # built only when clicked
        file_name=f"officemind-dashboard-{choice}-{datetime.now():%Y-%m-%d}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        icon=":material/download:",
        type="primary",
        width="stretch",
        on_click="ignore",  # downloading doesn't reload the page
    )

# ---------- Skeleton while the numbers are worked out ----------
body = st.empty()
body.markdown(
    '<div class="om-kpis">' + skeleton_html(lines=2, title=False) * 5 + "</div>"
    + skeleton_html(height=220) + "<br>" + skeleton_html(height=220),
    unsafe_allow_html=True,
)

stats = ticket_stats(days)
onboarding = onboarding_now(user)
asked, answered = question_count(days)
points, unit = tickets_over_time(days)
categories = tickets_by_category(days)
urgencies = tickets_by_urgency(days)
top = top_questions(days)
missing = unanswered_questions(days)
documents = document_count()

with body.container():
    # ---------- Stat cards ----------
    stat_cards([
        {"icon": "confirmation_number", "label": "Total tickets", "value": stats["total"],
         "note": range_label.lower()},
        {"icon": "pending_actions", "label": "Open tickets", "value": stats["open"],
         "note": "not closed yet", "tone": "amber" if stats["open"] else "green"},
        {"icon": "timer", "label": "Avg. time to close", "value": format_duration(stats["avg_close_hours"]),
         "note": f"{stats['closed']} closed" if stats["closed"] else "no tickets closed"},
        {"icon": "description", "label": "Documents", "value": documents, "note": "in the knowledge base"},
        {"icon": "group", "label": "Onboarding", "value": employees_onboarding(onboarding),
         "note": "employees in progress"},
    ])

    # ---------- Tickets over time (full width) ----------
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
                    line=dict(color=T["accent"], width=2),  # straight lines: a curve would invent values
                    marker=dict(size=8, color=T["accent"], line=dict(color=T["ring"], width=2)),
                    fill="tozeroy", fillcolor=T["fill"],
                    hovertemplate=f"%{{x|{label}}}<br><b>%{{y}}</b> new tickets<extra></extra>",
                )
            )
            style(fig, height=260).update_layout(hovermode="x")
            fig.update_xaxes(showspikes=True, spikemode="across", spikethickness=1,
                             spikecolor=T["axis"], spikedash="solid")
            fig.update_yaxes(rangemode="tozero", dtick=max(1, round(max(counts) / 4)))
            st.plotly_chart(fig, config=CHART_CONFIG, key="plot_time")

    # ---------- Category + urgency (side by side) ----------
    left, right = st.columns(2)
    with left:
        with chart_card("category", "Tickets by category", range_label):
            if not any(count for _, count in categories):
                no_data()
            else:
                fig = go.Figure(
                    go.Bar(
                        x=[c for c, _ in categories], y=[n for _, n in categories],
                        marker=dict(color=T["accent"]), width=0.5,
                        text=[n or "" for _, n in categories], textposition="outside",
                        textfont=dict(color=T["text"]), cliponaxis=False,
                        hovertemplate="%{x}<br><b>%{y}</b> tickets<extra></extra>",
                    )
                )
                style(fig).update_yaxes(rangemode="tozero", showticklabels=False, showgrid=False)
                st.plotly_chart(fig, config=CHART_CONFIG, key="plot_category")

    with right:
        with chart_card("urgency", "Tickets by urgency", range_label):
            if not any(count for _, count in urgencies):
                no_data()
            else:
                ordered = list(reversed(urgencies))  # High at the top of a horizontal chart
                fig = go.Figure(
                    go.Bar(
                        y=[URGENCIES[k] for k, _ in ordered], x=[n for _, n in ordered],
                        orientation="h", width=0.5,
                        marker=dict(color=[T["urgency"][k] for k, _ in ordered]),
                        text=[n or "" for _, n in ordered], textposition="outside",
                        textfont=dict(color=T["text"]), cliponaxis=False,
                        hovertemplate="%{y} urgency<br><b>%{x}</b> tickets<extra></extra>",
                    )
                )
                style(fig).update_xaxes(rangemode="tozero", showticklabels=False)
                fig.update_yaxes(showgrid=False, tickfont=dict(color=T["text"]))
                st.plotly_chart(fig, config=CHART_CONFIG, key="plot_urgency")

    # ---------- Onboarding progress ----------
    with chart_card("onboarding", "Onboarding progress", "Every new employee, right now"):
        if not onboarding:
            no_data("Nobody is onboarding yet.")
        else:
            rows = list(reversed(onboarding))  # first name at the top
            names = [f"{r['employee']} · {r['checklist']}" for r in rows]
            fig = go.Figure(
                go.Bar(
                    y=names, x=[r["percent"] for r in rows], orientation="h", width=0.45,
                    marker=dict(color=T["accent"]),
                    text=[f"{r['done']}/{r['total']} · {ONBOARDING_STATUSES[r['status']]}" for r in rows],
                    textposition="outside", textfont=dict(color=T["text"]), cliponaxis=False,
                    customdata=[[r["days_idle"]] for r in rows],
                    hovertemplate="%{y}<br><b>%{x}%</b> done · last activity %{customdata[0]} days ago<extra></extra>",
                )
            )
            style(fig, height=max(160, 46 * len(rows) + 40))
            fig.update_xaxes(range=[0, 135], showticklabels=False)  # room for the labels
            fig.update_yaxes(showgrid=False, tickfont=dict(color=T["text"]), automargin=True)
            st.plotly_chart(fig, config=CHART_CONFIG, key="plot_onboarding")
            stuck = [r for r in onboarding if r["status"] == "stuck"]
            if stuck:
                st.markdown(" ".join(onboarding_badge("stuck", f"{r['employee']} is stuck") for r in stuck),
                            unsafe_allow_html=True)

    # ---------- AI questions ----------
    left, right = st.columns(2)
    with left:
        with chart_card("questions", "Most-asked questions",
                        f"{asked} asked · {answered} answered from documents"):
            if not top:
                no_data("No questions asked in this period.")
            else:
                rows = list(reversed(top))
                short = [q["question"] if len(q["question"]) <= 42 else q["question"][:40] + "…" for q in rows]
                fig = go.Figure(
                    go.Bar(
                        y=short, x=[q["times"] for q in rows], orientation="h", width=0.5,
                        marker=dict(color=T["accent"]),
                        text=[q["times"] for q in rows], textposition="outside",
                        textfont=dict(color=T["text"]), cliponaxis=False,
                        customdata=[[q["question"], "yes" if q["answered"] else "no"] for q in rows],
                        hovertemplate="%{customdata[0]}<br><b>%{x}</b>× asked · answered: %{customdata[1]}<extra></extra>",
                    )
                )
                style(fig, height=max(180, 38 * len(rows) + 40))
                fig.update_xaxes(showticklabels=False, rangemode="tozero")
                fig.update_yaxes(showgrid=False, tickfont=dict(color=T["text"]), automargin=True)
                st.plotly_chart(fig, config=CHART_CONFIG, key="plot_questions")

    with right:
        with chart_card("unanswered", "Unanswered questions",
                        "The AI couldn't answer these from the documents. Consider adding a document."):
            if not missing:
                no_data("Every question was answered from the documents.")
            else:
                items = "".join(
                    f"""<li><span class="om-q-text">{html.escape(q['question'])}</span>
                        <span class="om-badge">{q['times']}×</span></li>"""
                    for q in missing
                )
                st.markdown(f'<ul class="om-q-list">{items}</ul>', unsafe_allow_html=True)

    # ---------- Code quality leaderboard ----------
    from modules.codereview.store import leaderboard, review_totals

    board = leaderboard(days)
    totals = review_totals(days)
    note = (f"{totals['reviews']} code review(s) · average {totals['average']:g}/10" if totals["reviews"]
            else "No code reviews in this period")
    if totals["secrets"]:
        note += f" · {totals['secrets']} secret(s) found in code"
    with chart_card("code", "Code quality leaderboard", note + " · average review score per person"):
        if not board:
            no_data("Nobody has reviewed code in this period yet.")
        else:
            rows = list(reversed(board))  # best at the top
            fig = go.Figure(
                go.Bar(
                    y=[f"{r['name']} · {r['department']}" for r in rows], x=[r["average"] for r in rows],
                    orientation="h", width=0.5, marker=dict(color=T["accent"]),
                    text=[f"{r['average']:g} · {r['reviews']} review{'s' if r['reviews'] != 1 else ''}" for r in rows],
                    textposition="outside", textfont=dict(color=T["text"]), cliponaxis=False,
                    customdata=[[r["best"], r["first"], r["latest"], r["critical"]] for r in rows],
                    hovertemplate=("%{y}<br><b>%{x}</b>/10 average · best %{customdata[0]}<br>"
                                   "first %{customdata[1]} → latest %{customdata[2]} · "
                                   "%{customdata[3]} critical problems<extra></extra>"),
                )
            )
            style(fig, height=max(160, 42 * len(rows) + 40))
            fig.update_xaxes(range=[0, 13], showticklabels=False)  # room for the labels
            fig.update_yaxes(showgrid=False, tickfont=dict(color=T["text"]), automargin=True)
            st.plotly_chart(fig, config=CHART_CONFIG, key="plot_code")
            improving = [r for r in board if (r["change"] or 0) > 0]
            if improving:
                st.markdown(" ".join(
                    f'<span class="om-chip">{icon("trending_up", 14)}{html.escape(r["name"])} '
                    f'{r["first"]:g} → {r["latest"]:g}</span>' for r in improving), unsafe_allow_html=True)
