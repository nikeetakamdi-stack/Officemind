"""Put a review together: rule checks + AI findings, a score out of 10, and the improved code."""

from core.config import CODE_LANGUAGES, CODE_MAX_KB
from modules.codereview import ai
from modules.codereview.checks import rule_checks
from modules.codereview.security import redact, scan

SEVERITY_ORDER = {"critical": 0, "warning": 1, "suggestion": 2}
SOURCE_ORDER = {"security": 0, "rule": 1, "company": 2, "ai": 3}


def check_input(code: str, language: str) -> str | None:
    """A problem with what was pasted/uploaded, or None if it's fine."""
    if not code or not code.strip():
        return "Paste some code or upload a file first."
    if len(code.encode("utf-8")) > CODE_MAX_KB * 1024:
        return f"The code is bigger than {CODE_MAX_KB} KB. Review one file or part of it at a time."
    if language not in CODE_LANGUAGES:
        return "Choose Python, JavaScript, Java or SQL."
    return None


def merge(fixed: list[dict], from_ai: list[dict]) -> list[dict]:
    """Rule findings first. An AI finding is dropped if a rule check already reported that line
    (the exact check is more reliable), or if the AI already reported the same line and kind."""
    lines = {f["line"] for f in fixed}
    taken = set()
    merged = list(fixed)
    for f in from_ai:
        if f["line"] in lines or (f["line"], f["category"]) in taken:
            continue
        taken.add((f["line"], f["category"]))
        merged.append(f)
    return sorted(merged, key=lambda f: (SEVERITY_ORDER[f["severity"]], f["line"], SOURCE_ORDER.get(f["source"], 9)))


def score(findings: list[dict]) -> float:
    """10 = no problems. Critical -2.5, Warning -1, Suggestion -0.3 (suggestions cost at most 2).
    Any Critical problem caps the score at 6."""
    count = counts(findings)
    value = 10 - 2.5 * count["critical"] - 1.0 * count["warning"] - min(2.0, 0.3 * count["suggestion"])
    if count["critical"]:
        value = min(value, 6)
    return round(max(0.0, value), 1)


def score_label(value: float) -> tuple[str, str]:
    """(word, colour tone) for a score."""
    if value >= 9:
        return "Excellent", "green"
    if value >= 7:
        return "Good", "green"
    if value >= 5:
        return "Needs work", "amber"
    return "Poor", "red"


def counts(findings: list[dict]) -> dict:
    result = {"critical": 0, "warning": 0, "suggestion": 0}
    for f in findings:
        result[f["severity"]] += 1
    return result


def quick_review(code: str, language: str, rules: dict | None = None) -> dict:
    """Exact checks only (rule checks + security scan, no AI): fast, and the same code always
    gets the same score. Used to re-check improved/converted code and to compare versions."""
    security = scan(code, language)
    found = merge(security["findings"] + rule_checks(code, language, rules), [])
    return {"findings": found, "score": score(found), "counts": counts(found), "secrets": security["secrets"]}


def full_review(code: str, language: str, rules: dict | None = None, use_ai: bool = True) -> dict:
    """Rule checks + AI. Returns findings, score, counts and whether the AI worked."""
    rules = rules or {}
    security = scan(code, language)
    fixed = security["findings"] + rule_checks(code, language, rules)
    from_ai, cut, ai_ok = [], False, True
    if use_ai:
        try:  # secrets are hidden (****) before the AI sees the code
            from_ai, cut = ai.review(redact(code, security["secrets"]), language, rules.get("custom", ""))
        except Exception:  # Ollama not running, etc.: the exact checks still work
            ai_ok = False
    found = merge(fixed, from_ai)
    return {"language": language, "findings": found, "score": score(found), "counts": counts(found),
            "ai_ok": ai_ok and use_ai, "cut": cut, "secrets": security["secrets"]}


def improved_version(code: str, language: str, findings: list[dict], rules: dict | None = None) -> dict:
    """The AI's corrected code, re-checked by the rule checks."""
    new_code, problems = ai.improve(redact(code), language, findings)
    check = quick_review(new_code, language, rules)
    before = quick_review(code, language, rules)
    return {"code": new_code, "problems": problems, "score_after": check["score"],
            "rule_score_before": before["score"], "still_found": check["findings"]}
