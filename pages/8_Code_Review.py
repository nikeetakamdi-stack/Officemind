"""Code Review page.

Review: paste or upload code, get problems by severity, a score and a fixed version.
Smart tools: explain, Big O, unit tests, comments, convert. Compare two versions.
History: your past reviews. Company rules: admins set the coding rules everyone is checked against.
"""

import hashlib
import html
import re

import streamlit as st

from core.config import CODE_LANGUAGES, CODE_MAX_KB
from core.ui import AI_OFFLINE, empty_state, friendly_error, icon, page_setup, skeleton_html
from modules.codereview import tools
from modules.codereview.checks import CATEGORIES, NAMING_STYLES, SEVERITIES
from modules.codereview.languages import detect_language, label, language_from_filename
from modules.codereview.review import check_input, full_review, improved_version, score_label
from modules.codereview.security import find_secrets, preview, redact
from modules.codereview.store import delete_review, get_review, get_rules, log_tool, my_reviews, save_review, save_rules
from modules.helpdesk.tickets import friendly_time

user = page_setup("pages/8_Code_Review.py", "Code Review", "code",
                  "Find bugs, security problems and messy code, get a fixed version, and more.")
admin = user["role"] == "admin"
state = st.session_state

SEVERITY_ICONS = {"critical": "error", "warning": "warning", "suggestion": "lightbulb"}
SOURCES = {"rule": ("Rule check", "rule"), "company": ("Company rule", "policy"),
           "security": ("Security scan", "shield"), "ai": ("AI · please check", "auto_awesome")}
EXTENSIONS = {"python": "py", "javascript": "js", "java": "java", "sql": "sql"}
LANGUAGE_PICK = ["auto"] + list(CODE_LANGUAGES)


# ---------- Building blocks ----------
def rich(text: str) -> str:
    """Escape text, then show `code` in backticks as code."""
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", html.escape(text))


def finding_card(f: dict, lines: list[str]) -> str:
    source, source_icon = SOURCES.get(f["source"], SOURCES["ai"])
    code_line = lines[f["line"] - 1].strip() if 0 < f["line"] <= len(lines) else ""
    if f["source"] == "security" and f["category"] == "security":
        code_line = redact(code_line)  # never show a secret again
    snippet = f'<div class="om-cr-line"><span>{f["line"]}</span>{html.escape(code_line[:160])}</div>' if code_line else ""
    return f"""<div class="om-cr-card om-cr-{f['severity']}">
      <div class="om-cr-card-top">
        <span class="om-cr-sev">{icon(SEVERITY_ICONS[f['severity']], 16)}{SEVERITIES[f['severity']]}</span>
        <span class="om-chip">Line {f['line']}</span>
        <span class="om-chip">{CATEGORIES.get(f['category'], f['category'])}</span>
        <span class="om-cr-source om-cr-source-{f['source']}">{icon(source_icon, 14)}{source}</span>
      </div>
      {snippet}
      <div class="om-cr-problem">{rich(f['problem'])}</div>
      <div class="om-cr-fix">{icon('build', 15)}<span><b>Fix:</b> {rich(f['fix'])}</span></div>
    </div>"""


def score_card(result: dict, note: str) -> None:
    value = result["score"]
    word, tone = score_label(value)
    c = result["counts"]
    chips = "".join(
        f'<span class="om-cr-count om-cr-count-{k}">{icon(SEVERITY_ICONS[k], 15)}{c[k]} {SEVERITIES[k]}</span>'
        for k in SEVERITIES)
    st.markdown(
        f"""<div class="om-cr-score-card">
          <div class="om-cr-ring om-cr-ring-{tone}" style="--p:{value * 10}">
            <div><b>{value:g}</b><span>/ 10</span></div></div>
          <div class="om-cr-score-text">
            <div class="om-cr-score-word">{word} code quality</div>
            <div class="om-muted">{html.escape(note)}</div>
            <div class="om-cr-counts">{chips}</div>
          </div></div>""",
        unsafe_allow_html=True,
    )


def show_findings(findings: list[dict], code: str, empty_text: str) -> None:
    lines = code.split("\n")
    if not findings:
        empty_state("check_circle", "No problems found", empty_text)
        return
    for severity, name in SEVERITIES.items():
        group = [f for f in findings if f["severity"] == severity]
        if group:
            st.markdown(f'<div class="om-cr-group om-cr-group-{severity}">{icon(SEVERITY_ICONS[severity])}'
                        f'{name} <span class="om-badge">{len(group)}</span></div>', unsafe_allow_html=True)
            st.markdown("".join(finding_card(f, lines) for f in group), unsafe_allow_html=True)


def secrets_banner(secrets: list[dict]) -> None:
    items = "".join(f"<li>Line {s['line']}: {html.escape(s['kind'])} <code>{html.escape(preview(s['value']))}</code></li>"
                    for s in secrets[:8])
    st.markdown(
        f"""<div class="om-cr-secret">{icon('key')}<div>
          <div class="om-cr-secret-title">{len(secrets)} secret{'s' if len(secrets) != 1 else ''} found in this code</div>
          <ul>{items}</ul>
          <div>Remove {'them' if len(secrets) != 1 else 'it'} from the code and <b>change (rotate)</b> {'them' if len(secrets) != 1 else 'it'}:
          anyone who saw this code could use {'them' if len(secrets) != 1 else 'it'}. OfficeMind hid
          {'them' if len(secrets) != 1 else 'it'} (****) before the AI saw the code and doesn't save
          {'them' if len(secrets) != 1 else 'it'}.</div></div></div>""",
        unsafe_allow_html=True)


def side_by_side(left_title: str, left: str, left_language: str, right_title: str, right: str,
                 right_language: str) -> None:
    a, b = st.columns(2)
    with a:
        st.markdown(f'<div class="om-cr-pane-title">{left_title}</div>', unsafe_allow_html=True)
        st.code(left, language=left_language, line_numbers=True)
    with b:
        st.markdown(f'<div class="om-cr-pane-title">{right_title}</div>', unsafe_allow_html=True)
        st.code(right, language=right_language, line_numbers=True)


def problems_list(problems: list[str]) -> None:
    for problem in problems:
        st.warning(problem, icon=":material/report:")


def busy(text: str):
    spot = st.empty()
    spot.markdown(skeleton_html(lines=5, label=text), unsafe_allow_html=True)
    return spot


def choose_language(choice: str, code: str, filename: str | None) -> tuple[str, str]:
    if choice != "auto":
        return choice, "chosen by you"
    if not code.strip():
        return "python", ""
    return detect_language(code, filename)


# ---------- The code to review ----------
def read_input() -> tuple[str, str | None, str | None]:
    """(code, file name, problem)"""
    mode = st.segmented_control("Add code", ["Paste code", "Upload a file"], default="Paste code",
                                key="cr_mode", label_visibility="collapsed") or "Paste code"
    if mode == "Paste code":
        return st.text_area("Your code", key="cr_paste", height=280,
                            placeholder="Paste Python, JavaScript, Java or SQL code here…"), None, None
    file = st.file_uploader("Code file (.py, .js, .java, .sql)", type=["py", "js", "java", "sql"], key="cr_upload",
                            help=f"Up to {CODE_MAX_KB} KB.")
    if not file:
        return "", None, None
    data = file.getvalue()
    if len(data) > CODE_MAX_KB * 1024:
        return "", file.name, f"That file is bigger than {CODE_MAX_KB} KB."
    code = data.decode("utf-8", errors="replace").replace("\r\n", "\n")
    with st.expander(f"{file.name} · {code.count(chr(10)) + 1} lines", icon=":material/description:"):
        st.code(redact(code), language=language_from_filename(file.name), line_numbers=True)
    return code, file.name, None


# ---------- Tool results ----------
def show_explain(r: dict, language: str) -> None:
    if not r["steps"]:
        st.info("The AI couldn't explain this code this time. Try again.", icon=":material/info:")
        return
    rows = "".join(
        f"""<div class="om-cr-step"><div class="om-cr-line"><span>{s['start']}</span>{html.escape(s['code'].strip()[:160])}</div>
            <div class="om-cr-step-text">{rich(s['text'])}</div></div>""" for s in r["steps"])
    st.markdown(f'<div class="om-cr-tool">{rows}</div>', unsafe_allow_html=True)
    if r["cut"]:
        st.caption(f"Only the first {tools.EXPLAIN_MAX_LINES} lines were explained.")


def show_bigo(r: dict) -> None:
    if r.get("sql"):
        st.info("Big O doesn't really apply to SQL: the database decides how to run a query. Speed depends on "
                "indexes and how much data is read. Look at the Performance cards in the review, and ask your "
                "database for its plan (`EXPLAIN` / `EXPLAIN PLAN FOR ...`).", icon=":material/info:")
        return
    loops = r["loops"]
    if r["estimate"]:
        check = (f"{icon('check_circle', 15)} The loop count agrees" if r["agrees"]
                 else f"{icon('help', 15)} The loop count suggests <b>{r['estimate']}</b>, so check this one by hand")
        loop_text = (f"{loops} loop{'s' if loops != 1 else ''} inside each other" if loops else "no loops") + \
                    (", plus sorting" if r["sorts"] else "") + (f", recursion in {', '.join(r['recursive'])}" if r["recursive"] else "")
    else:
        check, loop_text = "", ""
    st.markdown(
        f"""<div class="om-cr-tool om-cr-bigo">
          <div class="om-cr-bigo-tiles">
            <div><span>Time</span><b>{html.escape(r['time'] or '?')}</b></div>
            <div><span>Space</span><b>{html.escape(r['space'] or '?')}</b></div>
          </div>
          <div class="om-cr-problem">{rich(r['why'])}</div>
          <div class="om-muted om-cr-bigo-check">{check}{' · ' + loop_text if loop_text else ''}</div>
          {f'<div class="om-cr-fix">{icon("bolt", 15)}<span><b>Faster approach'
           + (f" ({html.escape(r['faster_time'])})" if r["faster_time"] else "") + f':</b> {rich(r["faster"])}</span></div>'
           if r["faster"] else ''}
          {f'<div class="om-cr-fix">{icon("lightbulb", 15)}<span><b>Tip:</b> {rich(r["tip"])}</span></div>' if r.get("tip") else ''}
        </div>""",
        unsafe_allow_html=True)


def show_code_result(r: dict, original: str, language: str, title: str, new_language: str, file_name: str,
                     key: str, note: str) -> None:
    problems_list(r.get("problems", []))
    st.caption(note)
    side_by_side("Original", original, language, title, r["code"], new_language)
    st.download_button(f"Download {title.lower()}", r["code"], file_name=file_name, icon=":material/download:",
                       on_click="ignore", key=f"cr_dl_{key}")


TOOLS = {"explain": ("Explain code", "school"), "bigo": ("Big O", "speed"), "tests": ("Unit tests", "science"),
         "comments": ("Comments & docstrings", "notes"), "convert": ("Convert", "translate")}


def run_tool(tool: str, code: str, language: str, target: str | None) -> dict:
    safe = redact(code)  # secrets never go to the AI
    if tool == "explain":
        return tools.explain(safe, language)
    if tool == "bigo":
        return tools.complexity(safe, language)
    if tool == "tests":
        return tools.unit_tests(safe, language)
    if tool == "comments":
        return tools.add_comments(safe, language)
    return tools.convert(safe, language, target)


def show_tool(tool: str, r: dict, code: str, language: str) -> None:
    name, tool_icon = TOOLS[tool]
    st.markdown(f'<div class="om-cr-group">{icon(tool_icon)}{name}'
                + (f' → {label(r["target"])}' if tool == "convert" else "") + "</div>", unsafe_allow_html=True)
    shown = redact(code)
    if tool == "explain":
        show_explain(r, language)
    elif tool == "bigo":
        show_bigo(r)
    elif tool == "tests":
        st.caption(f"{r['framework']} tests written by the AI. **These are drafts:** an expected value can be wrong. "
                   "Run them and check any that fail before you trust them. (OfficeMind never runs code you paste, "
                   "so it can't run them for you.)")
        problems_list(r["problems"])
        st.code(r["code"], language=language, line_numbers=True)
        st.download_button("Download tests", r["code"], file_name=r["file_name"], icon=":material/download:",
                           on_click="ignore", key="cr_dl_tests")
    elif tool == "comments":
        if r["same_logic"] and r["added"]:
            st.success("Only comments were added: your code itself is exactly the same (checked automatically).",
                       icon=":material/verified:")
        show_code_result(r, shown, language, "With comments", language, f"commented.{EXTENSIONS[language]}",
                         "comments", "The AI wrote the comment text; OfficeMind put it into your unchanged code.")
    elif tool == "convert":
        quick = r["review"]
        show_code_result(r, shown, language, label(r["target"]), r["target"], f"converted.{EXTENSIONS[r['target']]}",
                         "convert", f"Converted by the AI. Exact checks on the new code: {quick['score']:g}/10 · "
                         f"{quick['counts']['critical']} critical, {quick['counts']['warning']} warnings. "
                         "Test it before you use it.")


# =====================================================================
tab_names = [":material/rate_review: Review & tools", ":material/compare: Compare versions",
             ":material/history: My history"] + ([":material/policy: Company rules"] if admin else [])
tabs = st.tabs(tab_names)
rules = get_rules()

# ---------- Review & tools ----------
with tabs[0]:
    with st.container(key="cr_input"):
        code, filename, input_problem = read_input()
        pick_col, button_col = st.columns([2, 1], vertical_alignment="bottom")
        with pick_col:
            choice = st.selectbox("Language", LANGUAGE_PICK, key="cr_language",
                                  format_func=lambda k: "Auto-detect" if k == "auto" else CODE_LANGUAGES[k])
        with button_col:
            clicked = st.button("Review code", type="primary", icon=":material/rate_review:",
                                width="stretch", key="cr_review")
        language, how = choose_language(choice, code, filename)
        if code.strip() and choice == "auto":
            st.caption(f"Language: **{label(language)}** ({how}). Pick it above if that's wrong.")
        live_secrets = find_secrets(code) if code.strip() else []
        if live_secrets:  # warn straight away, before any review
            st.error(f"This code contains {len(live_secrets)} secret(s), e.g. a {live_secrets[0]['kind']} on line "
                     f"{live_secrets[0]['line']}. Remove it and change it, it isn't safe in code.",
                     icon=":material/key:")

    code_id = hashlib.sha256(f"{language}\n{code}".encode()).hexdigest()

    if clicked:
        problem = input_problem or check_input(code, language)
        if problem:
            st.warning(problem, icon=":material/info:")
        else:
            spot = busy("Checking the code… the AI usually takes 5–30 seconds.")
            result = full_review(code, language, rules)
            spot.empty()
            result.update(how=how, lines=code.count("\n") + 1, filename=filename)
            save_review(user, code, filename, result)
            state.cr = {"id": code_id, "code": code, "language": language, "result": result, "improved": None}

    review = state.get("cr")
    if review:
        result = review["result"]
        if review["id"] != code_id and code.strip():
            st.info("The code above has changed since this review. Click **Review code** to check it again.",
                    icon=":material/update:")
        if result.get("secrets"):
            secrets_banner(result["secrets"])
        score_card(result, f"{label(result['language'])} · {result['lines']} lines"
                           + (f" · {result['how']}" if result.get("how") else "") + " · saved to your history")
        if not result["ai_ok"]:
            friendly_error(AI_OFFLINE[0], "Showing the exact checks only. " + AI_OFFLINE[1])
        if result.get("cut"):
            st.info("This code is long, so the AI read only the first part. The exact checks read all of it.",
                    icon=":material/info:")
        show_findings(result["findings"], review["code"], "The checks and the AI didn't find anything to fix. Nice work!")

        if result["findings"]:
            if st.button("Show improved code", icon=":material/auto_fix_high:", key="cr_improve"):
                spot = busy("The AI is fixing the code, then the checks test its version…")
                try:
                    review["improved"] = improved_version(review["code"], review["language"], result["findings"], rules)
                    log_tool(user, "Improved code", review["language"])
                except Exception:
                    review["improved"] = None
                    friendly_error(*AI_OFFLINE)
                spot.empty()
        improved = review.get("improved")
        if improved:
            st.markdown(f'<div class="om-cr-compare-head">{icon("compare_arrows")} Exact-check score: '
                        f'<b>{improved["rule_score_before"]:g}</b> → <b>{improved["score_after"]:g}</b> / 10</div>',
                        unsafe_allow_html=True)
            show_code_result(improved, redact(review["code"]), review["language"], "Improved", review["language"],
                             f"improved.{EXTENSIONS[review['language']]}", "improved",
                             "Written by the AI and checked automatically. Read it and test it before you use it.")

    # ---------- Smart tools ----------
    st.markdown(f'<div class="om-cr-tools-title">{icon("handyman")} Smart tools '
                '<span class="om-muted">use the code above</span></div>', unsafe_allow_html=True)
    with st.container(key="cr_tools"):
        cols = st.columns([1, 1, 1, 1.35, 1.1, 0.9], vertical_alignment="bottom")
        pressed = None
        for col, tool in zip(cols[:4], ["explain", "bigo", "tests", "comments"]):
            name, tool_icon = TOOLS[tool]
            if col.button(name, icon=f":material/{tool_icon}:", key=f"cr_tool_{tool}", width="stretch"):
                pressed = tool
        targets = [k for k in CODE_LANGUAGES if k != language]
        target = cols[4].selectbox("Convert to", targets, key="cr_target", format_func=label)
        if cols[5].button("Convert", icon=":material/translate:", key="cr_tool_convert", width="stretch"):
            pressed = "convert"

    if pressed:
        problem = input_problem or check_input(code, language)
        if problem:
            st.warning(problem, icon=":material/info:")
        else:
            spot = busy(f"{TOOLS[pressed][0]}: the AI is working on it…")
            try:
                r = run_tool(pressed, code, language, target)
                r["target"] = target
                tools_state = state.get("cr_tools_results")
                if not tools_state or tools_state["id"] != code_id:
                    tools_state = {"id": code_id, "code": code, "language": language, "results": {}}
                tools_state["results"].pop(pressed, None)
                tools_state["results"][pressed] = r  # newest last
                state.cr_tools_results = tools_state
                log_tool(user, TOOLS[pressed][0] + (f" to {label(target)}" if pressed == "convert" else ""), language)
            except Exception:
                friendly_error(*AI_OFFLINE)
            spot.empty()

    tools_state = state.get("cr_tools_results")
    if tools_state and tools_state["results"]:
        if tools_state["id"] != code_id and code.strip():
            st.info("These results are for an earlier version of the code.", icon=":material/update:")
        for tool, r in reversed(list(tools_state["results"].items())):  # newest first
            show_tool(tool, r, tools_state["code"], tools_state["language"])

# ---------- Compare versions ----------
def use_improved() -> None:
    review = state.get("cr") or {}
    if review.get("improved"):
        state.cr_old = redact(review["code"])
        state.cr_new = review["improved"]["code"]
        state.cr_cmp_language = review["language"]


with tabs[1]:
    st.caption("Paste an old and a new version. Both are scored with the same exact checks (rule checks + security "
               "scan), so you can see fairly whether the quality went up.")
    if (state.get("cr") or {}).get("improved"):
        st.button("Use my last code and its improved version", icon=":material/content_copy:", on_click=use_improved,
                  key="cr_use_improved")
    left, right = st.columns(2)
    old = left.text_area("Old version", key="cr_old", height=260)
    new = right.text_area("New version", key="cr_new", height=260)
    pick_col, button_col = st.columns([2, 1], vertical_alignment="bottom")
    cmp_choice = pick_col.selectbox("Language", LANGUAGE_PICK, key="cr_cmp_language",
                                    format_func=lambda k: "Auto-detect" if k == "auto" else CODE_LANGUAGES[k])
    if button_col.button("Compare", type="primary", icon=":material/compare:", width="stretch", key="cr_compare"):
        cmp_language, _ = choose_language(cmp_choice, new or old, None)
        problem = check_input(old, cmp_language) or check_input(new, cmp_language)
        if problem:
            st.warning("Paste both versions first." if "Paste" in problem else problem, icon=":material/info:")
        else:
            state.cr_compare_result = {"result": tools.compare(old, new, cmp_language, rules), "old": old, "new": new,
                                "language": cmp_language}
            log_tool(user, "Compare versions", cmp_language)
    compared = state.get("cr_compare_result")
    if compared:
        c = compared["result"]
        change = c["change"]
        verdict, tone = (("Quality improved", "green") if change > 0 else ("Quality got worse", "red") if change < 0
                         else ("Quality stayed the same", "grey"))
        st.markdown(
            f"""<div class="om-cr-score-card om-cr-compare">
              <div class="om-cr-vs"><span>Old</span><b>{c['before']['score']:g}</b></div>
              <div class="om-cr-arrow">{icon('arrow_forward', 28)}</div>
              <div class="om-cr-vs"><span>New</span><b>{c['after']['score']:g}</b></div>
              <div class="om-cr-score-text">
                <div class="om-cr-score-word"><span class="om-cr-verdict om-cr-verdict-{tone}">{verdict}
                  {f'({change:+g})' if change else ''}</span></div>
                <div class="om-muted">{c['added']} line(s) added · {c['removed']} line(s) removed ·
                  {len(c['fixed'])} problem(s) fixed · {len(c['new'])} new problem(s)</div>
              </div></div>""",
            unsafe_allow_html=True)
        fixed_col, new_col = st.columns(2)
        with fixed_col:
            st.markdown(f'<div class="om-cr-group">{icon("check_circle")} Fixed '
                        f'<span class="om-badge">{len(c["fixed"])}</span></div>', unsafe_allow_html=True)
            if c["fixed"]:
                st.markdown("".join(finding_card(f, compared["old"].split("\n")) for f in c["fixed"]), unsafe_allow_html=True)
            else:
                st.caption("No problems from the old version were fixed.")
        with new_col:
            st.markdown(f'<div class="om-cr-group">{icon("report")} New '
                        f'<span class="om-badge">{len(c["new"])}</span></div>', unsafe_allow_html=True)
            if c["new"]:
                st.markdown("".join(finding_card(f, compared["new"].split("\n")) for f in c["new"]), unsafe_allow_html=True)
            else:
                st.caption("No new problems. 👍")
        st.markdown(f'<div class="om-cr-group">{icon("difference")} What changed</div>', unsafe_allow_html=True)
        diff = tools.diff_html(c["diff"])
        st.markdown(diff or '<div class="om-muted">The two versions are the same.</div>', unsafe_allow_html=True)

# ---------- History ----------
with tabs[2]:
    history = my_reviews(user)
    if not history:
        empty_state("history", "No reviews yet", "Every code review you run is saved here, so you can look back at it.")
    else:
        scores = [h["score"] for h in reversed(history)]
        st.caption(f"{len(history)} review(s) · average {sum(scores) / len(scores):.1f}/10"
                   + (f" · first {scores[0]:g} → latest {scores[-1]:g}" if len(scores) > 1 else "")
                   + " · only you can see your code")
        for h in history:
            word, tone = score_label(h["score"])
            title = f"{h['score']:g}/10 · {label(h['language'])} · {h['file_name'] or 'Pasted code'} · {h['lines']} lines · {friendly_time(h['created_at'])}"
            with st.expander(title, icon=":material/rate_review:"):
                saved = get_review(user, h["id"])
                chips = " ".join(f'<span class="om-cr-count om-cr-count-{k}">{n} {SEVERITIES[k]}</span>'
                                 for k, n in (("critical", h["critical"]), ("warning", h["warnings"]),
                                              ("suggestion", h["suggestions"])))
                st.markdown(f'<div class="om-cr-counts">{chips}</div>', unsafe_allow_html=True)
                if h["secrets"]:
                    st.caption(f"{h['secrets']} secret(s) were found in this code and hidden (****).")
                st.code(saved["code"], language=h["language"], line_numbers=True)
                show_findings(saved["findings"], saved["code"], "No problems were found in this review.")
                if st.button("Delete this review", icon=":material/delete:", key=f"cr_del_{h['id']}"):
                    delete_review(user, h["id"])
                    st.rerun()

# ---------- Company rules (admins) ----------
if admin:
    with tabs[3]:
        st.caption("Everyone's code is checked against these rules. Findings show as **Company rule**.")
        with st.form("cr_rules_form", border=False):
            naming = st.selectbox("Naming style", list(NAMING_STYLES), index=list(NAMING_STYLES).index(rules["naming"]),
                                  format_func=NAMING_STYLES.get)
            a, b = st.columns(2)
            function_lines = a.number_input("Longest function (lines, 0 = no limit)", 0, 1000,
                                            int(rules["max_function_lines"]))
            line_length = b.number_input("Longest line (characters, 0 = no limit)", 0, 500, int(rules["max_line_length"]))
            no_print = st.toggle("No print statements (print, console.log, System.out)", rules["no_print"])
            docstrings = st.toggle("Every function needs a docstring / doc comment", rules["require_docstrings"])
            custom = st.text_area("Extra rules in plain words (checked by the AI)", rules["custom"], height=110,
                                  placeholder="For example:\nUse the logging module, not print.\nNever catch an "
                                              "exception without logging it.")
            if st.form_submit_button("Save rules", type="primary", icon=":material/save:"):
                problem = save_rules(user, {"naming": naming, "max_function_lines": function_lines,
                                            "max_line_length": line_length, "no_print": no_print,
                                            "require_docstrings": docstrings, "custom": custom})
                if problem:
                    st.warning(problem, icon=":material/info:")
                else:
                    st.success("Rules saved. The next reviews use them.", icon=":material/check_circle:")
        st.caption("Exact rules (naming, length, print, docstrings) are always checked the same way. Extra rules in "
                   "plain words are checked by the AI, so treat those findings as hints.")
