"""Smart tools: explain, Big O, unit tests, comments/docstrings, convert, and compare two versions.

The AI writes the text and code; this file checks what it can before it's shown:
- explanations must point at real line numbers
- Big O is also estimated by counting nested loops, so you can see when the AI disagrees
- tests, commented code and converted code are checked for code that can't run
- "add comments" must leave the code itself exactly the same
- "compare" scores both versions with the same exact checks, so the scores are fair
"""

import ast
import difflib
import html
import re
import textwrap

from modules.codereview import ai
from modules.codereview.checks import _block_end, blank_comments_and_strings
from modules.codereview.languages import label
from modules.codereview.review import quick_review
from modules.codereview.verify import python_problems, rewrite_problems, sql_problems
from modules.security.masking import mask

EXPLAIN_MAX_LINES = 150
# Comments that judge the code instead of describing it (llama3.2 does this, and is often wrong)
JUDGING = re.compile(r"(?i)\b(should|could be|can be|unnecessary|not necessary|missing|optimi[sz]|simplif|"
                     r"instead|better|wrong|incorrect|error|bug|mistake|improve)\w*")
TEST_FRAMEWORKS = {"python": "pytest", "javascript": "Jest", "java": "JUnit 5", "sql": "plain SQL checks"}
TEST_FILE_NAMES = {"python": "test_code.py", "javascript": "code.test.js", "java": "CodeTest.java", "sql": "test_code.sql"}


# ---------- Explain ----------
def _find_line(item: dict, lines: list[str], used: set) -> int | None:
    """Which line the AI means: its line number if the quoted code matches, otherwise the first
    unused line with that code (the AI sometimes gives the code instead of the number)."""
    quote = ai._squash(str(item.get("code", "")) or str(item.get("line", "")))
    try:
        line = int(item.get("line"))
    except (TypeError, ValueError):
        line = None
    if line and 1 <= line <= len(lines) and (not quote or quote.isdigit() or quote in ai._squash(lines[line - 1])
                                             or ai._squash(lines[line - 1]) in quote):
        return line
    if quote and not quote.isdigit():
        for no, text in enumerate(lines, start=1):
            if no not in used and ai._squash(text) and (quote == ai._squash(text) or quote in ai._squash(text)):
                return no
    return None


def explain(code: str, language: str) -> dict:
    """Line-by-line explanation: {"steps": [{"start", "end", "code", "text"}], "cut": bool}"""
    lines = code.split("\n")
    text, _ = ai.numbered("\n".join(lines[:EXPLAIN_MAX_LINES]))
    wanted = [no for no, t in enumerate(lines[:EXPLAIN_MAX_LINES], start=1) if t.strip()]
    system = (f"You explain {label(language)} code to a complete beginner. {ai.DATA_RULE} For each line number you "
              "are given, write one short sentence in simple words that says what that line does (don't judge it). "
              'Reply in JSON: {"lines": [{"line": <line number>, "code": "<the text of that line>", '
              '"explanation": "<simple words>"}]}')
    steps, used = [], set()
    for _ in range(2):  # a second round for lines the AI skipped
        missing = [no for no in wanted if no not in used]
        if not missing:
            break
        data = ai.ask_json(system, f"Code (line numbers on the left):\n\n{text}\n\n"
                                   f"Explain each of these lines: {', '.join(map(str, missing[:60]))}")
        items = data.get("lines") or data.get("steps") or []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            explanation = str(item.get("explanation", "")).strip()
            line = _find_line(item, lines[:EXPLAIN_MAX_LINES], used)
            if not explanation or line is None or line in used or not lines[line - 1].strip() \
                    or re.search(r"(?i)\b(empty|blank) line\b|\bline is (blank|empty)\b", explanation):
                continue  # points at a line that isn't there
            used.add(line)
            steps.append({"start": line, "end": line, "code": lines[line - 1], "text": mask(explanation)})
    steps.sort(key=lambda s: s["start"])
    return {"steps": steps, "cut": len(lines) > EXPLAIN_MAX_LINES}


# ---------- Big O ----------
def loop_depth(code: str, language: str) -> dict:
    """Count how deeply loops are nested (2 loops inside each other ≈ O(n²)), and spot sorting and recursion."""
    depth, sorts, recursive = 0, False, []
    if language == "python":
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return {"depth": None, "sorts": False, "recursive": []}

        def walk(node, level):
            nonlocal depth
            for child in ast.iter_child_nodes(node):
                is_loop = isinstance(child, (ast.For, ast.AsyncFor, ast.While, ast.comprehension))
                depth = max(depth, level + is_loop)
                walk(child, level + is_loop)
        walk(tree, 0)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", "") or getattr(node.func, "attr", "")
                sorts = sorts or name in ("sorted", "sort")
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if any(isinstance(c, ast.Call) and getattr(c.func, "id", "") == node.name for c in ast.walk(node)):
                    recursive.append(node.name)
    elif language in ("javascript", "java"):
        clean = blank_comments_and_strings(code, language)
        stack, pending = [], 0
        for token in re.finditer(r"\b(for|while)\b|\.(forEach|map|filter|reduce)\(|[{}]", clean):
            if token.group(1) or token.group(2):
                pending += 1
            elif token.group(0) == "{":
                stack.append(pending > 0)
                pending = max(0, pending - 1)
                depth = max(depth, sum(stack))
            elif stack:
                stack.pop()
        sorts = bool(re.search(r"\.sort\(|Arrays\.sort|Collections\.sort", clean))
        for m in re.finditer(r"\bfunction\s+(\w+)|\b(?:public|private|protected|static)[\w\s<>\[\]]*?\s(\w+)\s*\(", clean):
            name = m.group(1) or m.group(2)
            start = clean.count("\n", 0, m.start()) + 1
            end = _block_end(clean, start)
            body = "\n".join(clean.split("\n")[start - 1:end or start])
            if name and len(re.findall(rf"\b{name}\s*\(", body)) > 1:  # it calls itself inside its own body
                recursive.append(name)
    else:
        return {"depth": None, "sorts": False, "recursive": []}
    return {"depth": depth, "sorts": sorts, "recursive": recursive}


def estimate_text(found: dict) -> str | None:
    depth = found.get("depth")
    if depth is None:
        return None
    if depth == 0:
        base = "O(1)" if not found["sorts"] else "O(n log n)"
    elif depth == 1:
        base = "O(n log n)" if found["sorts"] else "O(n)"
    else:
        base = f"O(n^{depth})"
    return base


def _normal(notation: str) -> str:
    return re.sub(r"\s+", "", notation or "").replace("²", "^2").replace("³", "^3").replace("**", "^").lower()


def complexity(code: str, language: str) -> dict:
    """{"time", "space", "why", "faster", "faster_time", "estimate", "agrees", "loops"}"""
    if language == "sql":
        return {"sql": True}
    found = loop_depth(code, language)
    estimate = estimate_text(found)
    text, _ = ai.numbered(code)
    system = (f"You are an expert in algorithms. {ai.DATA_RULE} Work out the Big O time and space complexity of this "
              f"{label(language)} code, where n is the size of the input. Explain why in simple words. If a faster "
              "approach exists (for example a set or dictionary instead of a loop inside a loop, sorting first, or "
              "stopping early), describe it in simple words with its Big O; otherwise say it is already efficient. "
              'Reply in JSON: {"time": "O(...)", "space": "O(...)", "why": "<simple words>", '
              '"faster": "<a faster approach, or empty>", "faster_time": "O(...) or empty"}')
    data = ai.ask_json(system, f"Code:\n\n{text}")
    result = {key: mask(str(data.get(key, "")).strip()) for key in ("time", "space", "why", "faster", "faster_time")}
    if re.fullmatch(r"(?i)(no|none|n/?a|-|already efficient\.?|it is already efficient\.?)?", result["faster"]):
        result["faster"], result["faster_time"] = "", ""
    result["tip"] = ""
    if (found["depth"] or 0) >= 2 and not result["faster"]:
        result["tip"] = ("There's a loop inside a loop. Often a set or a dictionary can remember what you've already "
                         "seen, so one pass is enough (O(n)), for example `seen = set()` and `if item in seen`.")
    result.update(estimate=estimate, loops=found["depth"], sorts=found["sorts"], recursive=found["recursive"],
                  agrees=bool(estimate) and _normal(estimate) == _normal(result["time"]))
    return result


# ---------- Unit tests ----------
def unit_tests(code: str, language: str) -> dict:
    """Tests written by the AI: {"code", "framework", "file_name", "problems"}"""
    framework = TEST_FRAMEWORKS[language]
    if language == "sql":
        how = ("Write SQL test checks: for each query, a short comment saying what it should return, then a SELECT "
               "that returns rows only when something is wrong (0 rows = test passed). Don't change any data.")
    else:
        how = (f"Write {framework} unit tests for every function: normal inputs, edge cases (empty, zero, None/null, "
               "very large) and wrong input. Import the code from a module called `code_under_test`" +
               (" (from code_under_test import ...)." if language == "python" else "."))
    system = (f"You are a senior {label(language)} developer who writes clear unit tests. {ai.DATA_RULE} {how} "
              f"Give every test a clear name. Reply with ONLY the test code in one ```{language} block.")

    def check(new):
        problems = rewrite_problems(code, new, language, keep_functions=False)
        if language == "python" and not problems and not re.search(r"^\s*def test_", new, re.MULTILINE):
            problems.append("It doesn't contain any test functions (def test_...).")
        return problems

    def with_import(new):  # a forgotten `import pytest` is added, not a reason to reject the tests
        if language == "python" and "pytest." in new and not re.search(r"^\s*import pytest", new, re.MULTILINE):
            new = "import pytest\n" + new
        return new

    tests, problems = ai._rewrite(system, f"Code to test:\n```{language}\n{code}\n```",
                                  lambda new: check(with_import(new)))
    tests = with_import(tests)
    return {"code": tests, "framework": framework, "file_name": TEST_FILE_NAMES[language], "problems": problems}


# ---------- Comments and docstrings ----------
def _without_comments(code: str, language: str) -> str:
    """The code with comments, docstrings and spacing removed, to check nothing else changed."""
    if language == "python":
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return "invalid:" + code
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if (isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and body
                    and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:] or [ast.Pass()]
        return ast.dump(tree)
    # comments removed, strings kept: any change to real code (strings included) is noticed
    return re.sub(r"\s+", "", blank_comments_and_strings(code, language, keep_strings=True))


def _documentable(code: str, language: str) -> list[dict]:
    """Functions/classes (or SQL statements) that should get a doc comment: [{"name", "line", "body_line"}]."""
    if language == "python":
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return []
        return [{"name": n.name, "line": n.lineno, "body_line": n.body[0].lineno}
                for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and not ast.get_docstring(n) and n.body[0].lineno > n.lineno]
    if language == "sql":
        from modules.codereview.checks import sql_statements
        return [{"name": f"statement on line {line}", "line": line} for line, _ in sql_statements(code)]
    clean = blank_comments_and_strings(code, language).split("\n")
    raw = code.split("\n")
    found = []
    for no, text in enumerate(clean, start=1):
        m = re.search(r"\bfunction\s+(\w+)|\b(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:function\b|\([^)]*\)\s*=>)", text) \
            if language == "javascript" else \
            re.search(r"\bclass\s+(\w+)|^\s*(?:(?:public|private|protected|static|final|abstract|synchronized)\s+)+[\w<>\[\],.\s]*?\s(\w+)\s*\(", text)
        if m and not (no > 1 and raw[no - 2].strip().endswith("*/")):
            found.append({"name": m.group(1) or m.group(2), "line": no})
    return found


def _indent(text: str) -> str:
    return text[: len(text) - len(text.lstrip())]


def _insert_comments(code: str, language: str, docs: dict, notes: dict) -> str:
    """Put the AI's comment text into the original code. Only comments are added; the code
    lines themselves are never touched."""
    lines = code.split("\n")
    targets = _documentable(code, language)
    inserts = []  # (line number to insert before, [new lines])
    starts = set()
    if language == "python":
        try:
            starts = {n.lineno for n in ast.walk(ast.parse(code)) if isinstance(n, ast.stmt)}
        except SyntaxError:
            return code
    for t in targets:
        text = docs.get(t["name"])
        if not text:
            continue
        wrapped = textwrap.wrap(text.replace('"""', "'''").replace("\\", "/").replace("*/", "* /"), 88) or [text]
        if language == "python":
            pad = _indent(lines[t["body_line"] - 1])
            body = [pad + '"""' + wrapped[0]] + [pad + w for w in wrapped[1:]]
            body[-1] += '"""'
            inserts.append((t["body_line"], body))
        elif language == "sql":
            inserts.append((t["line"], [_indent(lines[t["line"] - 1]) + "-- " + w for w in wrapped]))
        else:
            at = t["line"]
            while at > 1 and lines[at - 2].strip().startswith("@"):  # above annotations like @Override
                at -= 1
            pad = _indent(lines[at - 1])
            inserts.append((at, [pad + "/**"] + [pad + " * " + w for w in wrapped] + [pad + " */"]))
    marker = {"python": "#", "sql": "--"}.get(language, "//")
    taken = {at for at, _ in inserts} | {t["line"] for t in targets if docs.get(t["name"])}
    for line, text in notes.items():
        if line in taken or not 1 <= line <= len(lines) or not lines[line - 1].strip():
            continue
        if language == "python" and line not in starts:
            continue  # only above the start of a statement, never inside a string or a bracket
        inserts.append((line, [_indent(lines[line - 1]) + f"{marker} " + text.replace("\n", " ").replace("*/", "")]))
    for at, new in sorted(inserts, key=lambda i: i[0], reverse=True):
        lines[at - 1:at - 1] = new
    return "\n".join(lines)


def _match_docs(docs: dict, targets: list[dict]) -> dict:
    """Link the AI's doc texts to the real functions. The AI sometimes writes "check method"
    instead of "check", or its own names for SQL statements; then the order is used."""
    matched = {}
    for t in targets:
        name = t["name"].lower()
        for given, text in docs.items():
            if given.lower() == name or re.search(rf"\b{re.escape(name)}\b", given.lower()):
                matched[t["name"]] = text
                break
    if len(matched) < len(targets) and len(docs) == len(targets):
        for t, text in zip(targets, docs.values()):
            matched.setdefault(t["name"], text)
    return matched


def add_comments(code: str, language: str) -> dict:
    """{"code", "same_logic", "problems", "added"}: the AI only writes the comment text; the program puts
    it into your unchanged code, then checks that the code itself is exactly the same."""
    targets = _documentable(code, language)
    kind = "docstring" if language == "python" else "doc comment"
    names = ", ".join(t["name"] for t in targets) or "none"
    text, _ = ai.numbered(code)
    system = (f"You are a senior {label(language)} developer writing documentation in simple words. {ai.DATA_RULE} "
              f"Write a {kind} for each of these: {names}. Say what it does, what goes in and what comes out, in "
              "1 to 3 short sentences. Also write short comments for up to 8 lines that are hard to understand: "
              "each comment only describes what the line does, it never judges or suggests changes. "
              'Reply in JSON: {"docs": [{"name": "<name>", "text": "<doc text>"}], '
              '"comments": [{"line": <line number>, "code": "<text of that line>", "text": "<comment>"}]}')
    data = ai.ask_json(system, f"Code (line numbers on the left):\n\n{text}")
    lines = code.split("\n")
    docs = {str(d.get("name", "")).strip(): mask(str(d.get("text", "")).strip())
            for d in data.get("docs", []) if isinstance(d, dict)} if isinstance(data.get("docs"), list) else {}
    notes, used = {}, set()
    for item in data.get("comments", []) if isinstance(data.get("comments"), list) else []:
        if isinstance(item, dict) and str(item.get("text", "")).strip() and not JUDGING.search(str(item["text"])):
            line = _find_line(item, lines, used)
            if line:
                used.add(line)
                notes[line] = mask(str(item["text"]).strip())[:160]
    target = _without_comments(code, language)
    docs = _match_docs(docs, targets)
    new = _insert_comments(code, language, docs, notes)
    if _without_comments(new, language) != target:  # a comment landed somewhere unsafe: keep only the docs
        new = _insert_comments(code, language, docs, {})
    same = _without_comments(new, language) == target
    if not same:
        new = code
    added = new.count("\n") - code.count("\n")
    problems = [] if added else ["The AI didn't write any comments this time. Try again."]
    return {"code": new, "same_logic": same, "problems": problems, "added": added}


# ---------- Convert ----------
def convert(code: str, source: str, target: str) -> dict:
    """{"code", "problems", "review"}: the converted code, its problems, and a quick check of it."""
    if source == target:
        raise ValueError("Pick a different language to convert to.")
    if "sql" in (source, target):
        note = ("If the code is SQL, convert the queries into code that runs them with parameters (no string "
                "building). If the target is SQL, write the equivalent queries.")
    else:
        note = "Use the normal style of the new language (naming, error handling, standard library)."
    system = (f"You convert {label(source)} code to {label(target)}. {ai.DATA_RULE} Keep exactly the same behaviour. "
              f"{note} Never put passwords, keys or tokens in the code. "
              f"Reply with ONLY the complete {label(target)} code in one ```{target} block.")

    def check(new):
        return rewrite_problems(code, new, target, same_language=False)

    new, problems = ai._rewrite(system, f"{label(source)} code:\n```{source}\n{code}\n```", check)
    return {"code": new, "problems": problems, "review": quick_review(new, target)}


# ---------- Compare two versions ----------
def _key(f: dict) -> tuple:
    return (f["source"], f["category"], re.sub(r"\d+", "#", f["problem"]))


def compare(old: str, new: str, language: str, rules: dict | None = None) -> dict:
    """What changed between two versions, and did quality go up? Both are scored by the same
    exact checks (rule checks + security scan), so the comparison is fair."""
    before = quick_review(old, language, rules)
    after = quick_review(new, language, rules)
    old_keys = {_key(f) for f in before["findings"]}
    new_keys = {_key(f) for f in after["findings"]}
    diff = list(difflib.unified_diff(old.split("\n"), new.split("\n"), lineterm="", n=2))
    added = sum(1 for d in diff if d.startswith("+") and not d.startswith("+++"))
    removed = sum(1 for d in diff if d.startswith("-") and not d.startswith("---"))
    return {
        "before": before, "after": after, "diff": diff, "added": added, "removed": removed,
        "fixed": [f for f in before["findings"] if _key(f) not in new_keys],
        "new": [f for f in after["findings"] if _key(f) not in old_keys],
        "change": round(after["score"] - before["score"], 1),
    }


def diff_html(diff: list[str]) -> str:
    """The changes as coloured lines: green = added, red = removed."""
    rows = []
    for line in diff[2:] if len(diff) > 2 else []:
        if line.startswith("@@"):
            match = re.match(r"@@ -(\d+)", line)
            rows.append(f'<div class="om-diff-hunk">Around line {match.group(1) if match else "?"}</div>')
        elif line.startswith("+"):
            rows.append(f'<div class="om-diff-add"><span>+</span>{html.escape(line[1:]) or " "}</div>')
        elif line.startswith("-"):
            rows.append(f'<div class="om-diff-del"><span>−</span>{html.escape(line[1:]) or " "}</div>')
        else:
            rows.append(f'<div class="om-diff-same"><span> </span>{html.escape(line[1:]) or " "}</div>')
    return f'<div class="om-diff">{"".join(rows)}</div>' if rows else ""
