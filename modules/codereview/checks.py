"""Rule checks: fixed tests that find common problems without the AI.

These are exact: if a rule check reports something, it's really in the code.
Python is read properly (with Python's own `ast` parser). JavaScript, Java and
SQL are checked with text patterns after comments and strings are blanked out,
so a word inside a comment or a string doesn't count.

Every problem found is a "finding":
    {"line", "severity", "category", "problem", "fix", "source"}
severity: critical | warning | suggestion
source:   rule (built-in check) | company (a company coding rule) | ai | security
"""

import ast
import re

SEVERITIES = {"critical": "Critical", "warning": "Warning", "suggestion": "Suggestion"}
CATEGORIES = {"bug": "Bug", "security": "Security", "practice": "Bad practice",
              "readability": "Readability", "performance": "Performance", "rule": "Company rule"}

DEFAULT_RULES = {
    "naming": "default",          # default | snake_case | camelCase | off
    "no_print": False,            # no print / console.log / System.out
    "max_function_lines": 50,     # 0 = don't check
    "max_line_length": 120,       # 0 = don't check
    "require_docstrings": False,  # every function needs a docstring / doc comment
    "custom": "",                 # extra rules in plain words, checked by the AI
}
NAMING_STYLES = {
    "default": "Language standard (snake_case in Python and SQL, camelCase in JavaScript and Java)",
    "snake_case": "snake_case everywhere (total_price)",
    "camelCase": "camelCase everywhere (totalPrice)",
    "off": "Don't check names",
}
SNAKE = re.compile(r"^_{0,2}[a-z][a-z0-9_]*_{0,2}$")
CAMEL = re.compile(r"^_?[a-z][a-zA-Z0-9]*$")
PASCAL = re.compile(r"^_?[A-Z][a-zA-Z0-9]*$")
UPPER = re.compile(r"^_?[A-Z][A-Z0-9_]*$")


def finding(line: int, severity: str, category: str, problem: str, fix: str, source: str = "rule") -> dict:
    return {"line": max(1, int(line or 1)), "severity": severity, "category": category,
            "problem": problem, "fix": fix, "source": source}


# ---------- Helpers ----------
def blank_comments_and_strings(code: str, language: str, keep_strings: bool = False) -> str:
    """Same code with the inside of comments and strings replaced by spaces
    (line breaks kept, so line numbers stay right). keep_strings=True blanks only comments."""
    out, i, n = [], 0, len(code)
    line_comment = "--" if language == "sql" else "//"
    quotes = "'\"" + ("`" if language == "javascript" else "")
    if language == "python":
        line_comment, quotes = "#", "'\""
    while i < n:
        ch = code[i]
        if code.startswith(line_comment, i):
            end = code.find("\n", i)
            end = n if end == -1 else end
            out.append(" " * (end - i)); i = end
        elif language != "python" and code.startswith("/*", i):
            end = code.find("*/", i + 2)
            end = n if end == -1 else end + 2
            out.append(re.sub(r"[^\n]", " ", code[i:end])); i = end
        elif ch in quotes:
            triple = language == "python" and code.startswith(ch * 3, i)
            closer = ch * 3 if triple else ch
            j = i + len(closer)
            while j < n and not code.startswith(closer, j):
                if code[j] == "\\" and language != "sql":
                    j += 1
                elif code[j] == "\n" and not triple and ch != "`":
                    break
                j += 1
            end = min(n, j + len(closer))
            inside = code[i + len(closer):j] if keep_strings else re.sub(r"[^\n]", " ", code[i + len(closer):j])
            out.append(closer + inside + (closer if j < n else ""))
            i = end
        else:
            out.append(ch); i += 1
    return "".join(out)


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _block_end(clean: str, start_line: int) -> int | None:
    """Line where the { ... } block that opens on (or just after) start_line closes."""
    lines = clean.split("\n")
    offset = sum(len(l) + 1 for l in lines[: start_line - 1])
    first = clean.find("{", offset)
    if first == -1 or _line_of(clean, first) > start_line + 2:
        return None
    depth = 0
    for k in range(first, len(clean)):
        if clean[k] == "{":
            depth += 1
        elif clean[k] == "}":
            depth -= 1
            if depth == 0:
                return _line_of(clean, k)
    return None


def _one_argument(text: str, start: int) -> bool:
    """True if the call whose ( ends at `start` has a single argument (no top-level comma)."""
    depth = 1
    for ch in text[start:]:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                return True
        elif ch == "," and depth == 1:
            return False
    return False


def naming_style(rules: dict, language: str) -> str | None:
    style = rules.get("naming", "default")
    if style == "off":
        return None
    if style == "default":
        return "snake_case" if language in ("python", "sql") else "camelCase"
    return style


def _bad_name(name: str, style: str) -> bool:
    if UPPER.match(name) or len(name) == 1 or name.startswith("__"):
        return False  # constants, i/j/x, and Python's own __names__ are fine
    return not (SNAKE if style == "snake_case" else CAMEL).match(name)


def _name_fix(name: str, style: str) -> str:
    words = re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", name) or [name]
    if style == "snake_case":
        return "_".join(w.lower() for w in words)
    return words[0].lower() + "".join(w.capitalize() for w in words[1:])


# ---------- Python ----------
BUILTINS = {"list", "dict", "str", "int", "float", "set", "tuple", "id", "input", "type", "sum",
            "max", "min", "len", "file", "object", "filter", "map", "open", "range", "format", "hash"}


def _python(code: str, lines: list[str], rules: dict) -> list[dict]:
    try:
        tree = ast.parse(code)
    except SyntaxError as error:
        return [finding(error.lineno or 1, "critical", "bug",
                        f"Python can't read this code: {error.msg}.",
                        "Fix the typing mistake on this line, e.g. a missing bracket, colon, quote or wrong indentation.")]
    found = []
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    imported, used = {}, set()
    style = naming_style(rules, "python")
    named = set()

    def check_name(name, line, kind):
        if style and name not in named and _bad_name(name, style):
            named.add(name)
            found.append(finding(line, "suggestion", "rule",
                                 f"The {kind} name `{name}` doesn't follow the company naming style ({style}).",
                                 f"Rename it to `{_name_fix(name, style)}`.", "company"))

    for node in ast.walk(tree):
        line = getattr(node, "lineno", 1)
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            base = node
            while isinstance(base, ast.Attribute):
                base = base.value
            if isinstance(base, ast.Name):
                used.add(base.id)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                name = (alias.asname or alias.name).split(".")[0]
                if name != "*":
                    imported.setdefault(name, line)

        if isinstance(node, ast.ExceptHandler):
            if node.type is None:
                found.append(finding(line, "warning", "practice",
                                     "`except:` with nothing after it catches every error, even typing mistakes and Ctrl+C, so real bugs get hidden.",
                                     "Catch only the error you expect, e.g. `except ValueError:`."))
            if all(isinstance(s, ast.Pass) for s in node.body):
                found.append(finding(line, "warning", "practice",
                                     "The error is caught and silently ignored (`pass`), so nobody will know something went wrong.",
                                     "Log the error, show a message, or let it go up instead of ignoring it."))

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for default in node.args.defaults + node.args.kw_defaults:
                if isinstance(default, (ast.List, ast.Dict, ast.Set)) or (
                        isinstance(default, ast.Call) and getattr(default.func, "id", "") in ("list", "dict", "set")):
                    found.append(finding(default.lineno, "warning", "bug",
                                         f"`{node.name}` uses a list/dict as a default value. Python creates it only once, so it keeps values between calls.",
                                         "Use `None` as the default and create the list inside: `if items is None: items = []`."))
            length = (node.end_lineno or line) - line + 1
            limit = int(rules.get("max_function_lines") or 0)
            if limit and length > limit:
                found.append(finding(line, "suggestion", "rule",
                                     f"The function `{node.name}` is {length} lines long; the company limit is {limit}.",
                                     "Split it into smaller functions that each do one job.", "company"))
            if rules.get("require_docstrings") and not ast.get_docstring(node):
                found.append(finding(line, "suggestion", "rule",
                                     f"The function `{node.name}` has no docstring (company rule).",
                                     'Add a short description as the first line: `"""What this function does."""`.', "company"))
            check_name(node.name, line, "function")
            for arg in node.args.args + node.args.kwonlyargs:
                if arg.arg not in ("self", "cls"):
                    check_name(arg.arg, arg.lineno, "parameter")

        elif isinstance(node, ast.ClassDef):
            if style and not PASCAL.match(node.name):
                found.append(finding(line, "suggestion", "readability",
                                     f"The class name `{node.name}` should start with a capital letter (PascalCase).",
                                     f"Rename it to `{node.name[:1].upper() + _name_fix(node.name, 'camelCase')[1:]}`."))
            if rules.get("require_docstrings") and not ast.get_docstring(node):
                found.append(finding(line, "suggestion", "rule", f"The class `{node.name}` has no docstring (company rule).",
                                     'Add a short description as the first line of the class.', "company"))

        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for item in ast.walk(target):
                    if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store):
                        if item.id in BUILTINS:
                            found.append(finding(line, "suggestion", "practice",
                                                 f"The variable `{item.id}` hides Python's built-in `{item.id}()`, which then stops working in this code.",
                                                 f"Use a clearer name, e.g. `{item.id}_value` or `my_{item.id}`."))
                        else:
                            check_name(item.id, line, "variable")

        elif isinstance(node, ast.Compare):
            for op, right in zip(node.ops, node.comparators):
                if isinstance(right, ast.Constant):
                    if isinstance(op, (ast.Eq, ast.NotEq)) and right.value is None:
                        found.append(finding(line, "suggestion", "practice", "Comparing with `None` using `==`.",
                                             "Use `is None` / `is not None`."))
                    elif isinstance(op, (ast.Eq, ast.NotEq)) and isinstance(right.value, bool):
                        found.append(finding(line, "suggestion", "readability", "Comparing with `True`/`False` isn't needed.",
                                             "Write `if done:` or `if not done:`."))
                    elif isinstance(op, (ast.Is, ast.IsNot)) and right.value is not None and not isinstance(right.value, bool):
                        found.append(finding(line, "warning", "bug",
                                             "`is` checks if two things are the same object, not the same value, so this can be False even when the values match.",
                                             "Use `==` (or `!=`) to compare values."))

        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)):
            if isinstance(node.right, ast.Constant) and node.right.value == 0:
                found.append(finding(line, "critical", "bug", "Dividing by zero always crashes the program.",
                                     "Check the number isn't 0 before dividing."))

        elif isinstance(node, ast.For):
            it = node.iter
            if (isinstance(it, ast.Call) and getattr(it.func, "id", "") == "range" and len(it.args) == 1
                    and isinstance(it.args[0], ast.Call) and getattr(it.args[0].func, "id", "") == "len"):
                found.append(finding(line, "suggestion", "readability", "`for i in range(len(...))` is harder to read than needed.",
                                     "Loop over the items directly, or use `for i, item in enumerate(items):`."))

        elif isinstance(node, ast.Global):
            found.append(finding(line, "suggestion", "practice",
                                 "`global` lets a function change variables outside it, which makes bugs hard to follow.",
                                 "Pass the value in as a parameter and return the new value."))

        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", "")
            if name == "open" and not isinstance(parents.get(node), ast.withitem):
                found.append(finding(line, "suggestion", "practice",
                                     "The file is opened without `with`, so it may stay open if an error happens.",
                                     "Use `with open(...) as f:` so the file is always closed."))
            if name == "print" and rules.get("no_print"):
                found.append(finding(line, "suggestion", "rule", "`print()` isn't allowed by the company rules.",
                                     "Use the `logging` module instead, e.g. `logging.info(...)`.", "company"))

        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if isinstance(block, list):
                for k, stmt in enumerate(block[:-1]):
                    if isinstance(stmt, (ast.Return, ast.Raise, ast.Continue, ast.Break)):
                        found.append(finding(block[k + 1].lineno, "warning", "bug",
                                             "This line can never run: the line before it always leaves the block.",
                                             "Remove it, or move it above the `return`/`raise`/`break`/`continue`."))
                        break

    for name, line in imported.items():
        if name not in used and not re.search(rf"__all__.*['\"]{re.escape(name)}['\"]", code):
            found.append(finding(line, "suggestion", "readability", f"`{name}` is imported but never used.",
                                 "Remove the unused import."))
    return found


# ---------- JavaScript and Java ----------
JS_FUNCTION = re.compile(r"\bfunction\s+(\w+)\s*\(|\b(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:function\b|\([^)]*\)\s*=>|\w+\s*=>)")
JS_VARIABLE = re.compile(r"\b(?:const|let|var)\s+(\w+)\s*=")
JAVA_METHOD = re.compile(r"^\s*(?:(?:public|private|protected|static|final|abstract|synchronized)\s+)*"
                         r"(?:<[^>]+>\s+)?[\w.]+(?:<[^>]*>)?(?:\[\])*\s+(\w+)\s*\([^;{]*\)\s*(?:throws\s+[\w.,\s]+)?\{?\s*$")
JAVA_VARIABLE = re.compile(r"^\s*(?:final\s+)?(?:int|long|double|float|boolean|char|byte|short|String|var)\s+(\w+)\s*[=;]")
KEYWORDS = {"if", "for", "while", "switch", "catch", "return", "new", "else", "function", "do", "try", "synchronized"}


def _c_like(code: str, lines: list[str], language: str, rules: dict) -> list[dict]:
    found = []
    clean = blank_comments_and_strings(code, language)
    clean_lines = clean.split("\n")
    style = naming_style(rules, language)
    limit = int(rules.get("max_function_lines") or 0)
    named = set()

    def documented(line_no):
        for back in range(line_no - 2, max(-1, line_no - 4), -1):
            prev = lines[back].strip()
            if prev.startswith("@"):
                continue
            return prev.endswith("*/")
        return False

    def check_function(name, line_no, kind="function"):
        end = _block_end(clean, line_no)
        if limit and end and end - line_no + 1 > limit:
            found.append(finding(line_no, "suggestion", "rule",
                                 f"The {kind} `{name}` is {end - line_no + 1} lines long; the company limit is {limit}.",
                                 "Split it into smaller functions that each do one job.", "company"))
        if rules.get("require_docstrings") and not documented(line_no):
            found.append(finding(line_no, "suggestion", "rule", f"The {kind} `{name}` has no doc comment (company rule).",
                                 "Add a `/** What it does, its parameters and what it returns. */` comment above it.", "company"))
        check_name(name, line_no, kind)

    def check_name(name, line_no, kind):
        if style and name not in named and not PASCAL.match(name) and _bad_name(name, style):
            named.add(name)
            found.append(finding(line_no, "suggestion", "rule",
                                 f"The {kind} name `{name}` doesn't follow the company naming style ({style}).",
                                 f"Rename it to `{_name_fix(name, style)}`.", "company"))

    for no, (raw, text) in enumerate(zip(lines, clean_lines), start=1):
        if re.search(r"\bcatch\s*(\([^)]*\))?\s*\{\s*\}", text) or (
                re.search(r"\bcatch\s*(\([^)]*\))?\s*\{\s*$", text) and no < len(clean_lines)
                and clean_lines[no].strip() == "}"):
            found.append(finding(no, "warning", "practice", "The error is caught and silently ignored (empty `catch`).",
                                 "Log the error or handle it, so problems don't disappear."))
        if language == "javascript":
            if re.search(r"(?<![=!<>])[=!]=(?!=)", text):
                found.append(finding(no, "warning", "bug",
                                     "`==` changes types before comparing (for example `'0' == 0` is true), which causes surprising bugs.",
                                     "Use `===` (and `!==`) instead."))
            if re.search(r"\bvar\s+\w", text):
                found.append(finding(no, "suggestion", "practice", "`var` is old JavaScript and can leak outside its block.",
                                     "Use `const` (or `let` if the value changes)."))
            if any(_one_argument(text, m.end()) for m in re.finditer(r"\bparseInt\(", text)):
                found.append(finding(no, "suggestion", "bug", "`parseInt` without a number base can read some text wrongly.",
                                     "Pass the base: `parseInt(value, 10)`."))
            if rules.get("no_print") and re.search(r"\bconsole\.(log|debug|info)\(", text):
                found.append(finding(no, "suggestion", "rule", "`console.log` isn't allowed by the company rules.",
                                     "Remove it or use the project's logger.", "company"))
            functions = {m.group(1) or m.group(2) for m in JS_FUNCTION.finditer(text)}
            for name in functions:
                check_function(name, no)
            for match in JS_VARIABLE.finditer(text):
                if match.group(1) not in functions:
                    check_name(match.group(1), no, "variable")
        else:  # Java
            if re.search(r'==\s*"|"\s*==|!=\s*"|"\s*!=', raw):
                found.append(finding(no, "warning", "bug", "`==` compares whether two Strings are the same object, not the same text.",
                                     'Use `.equals(...)`, e.g. `"yes".equals(answer)`.'))
            if re.search(r"\.printStackTrace\(\)", text):
                found.append(finding(no, "suggestion", "practice", "`printStackTrace()` only prints the error to the console.",
                                     "Use a logger, e.g. `logger.error(\"...\", e)`."))
            if re.search(r"\bcatch\s*\(\s*(Exception|Throwable)\s+\w+\s*\)", text):
                found.append(finding(no, "suggestion", "practice", "Catching every `Exception` can hide errors you didn't expect.",
                                     "Catch the specific exception, e.g. `IOException`."))
            if rules.get("no_print") and re.search(r"\bSystem\.(out|err)\.print", text):
                found.append(finding(no, "suggestion", "rule", "`System.out.println` isn't allowed by the company rules.",
                                     "Use a logger instead.", "company"))
            method = JAVA_METHOD.match(text)
            if method and method.group(1) not in KEYWORDS and not re.match(r"^\s*(return|new|else)\b", text):
                check_function(method.group(1), no, "method")
            variable = JAVA_VARIABLE.match(text)
            if variable and "final" not in text:
                check_name(variable.group(1), no, "variable")
            klass = re.search(r"\bclass\s+(\w+)", text)
            if klass and not PASCAL.match(klass.group(1)):
                found.append(finding(no, "suggestion", "readability", f"The class name `{klass.group(1)}` should start with a capital letter.",
                                     "Rename it in PascalCase, e.g. `OrderService`."))
    return found


# ---------- SQL ----------
def sql_spans(code: str) -> list[tuple[int, int]]:
    """Where each SQL statement starts and ends in the text: [(start, end)], end includes the ;"""
    clean = blank_comments_and_strings(code, "sql")
    spans, start = [], 0
    for match in re.finditer(r";|$", clean):
        piece = clean[start:match.start()]
        if piece.strip():
            lead = len(piece) - len(piece.lstrip())
            spans.append((start + lead, match.end()))
        start = match.end()
        if match.end() >= len(clean):
            break
    return spans


def sql_statements(code: str) -> list[tuple[int, str]]:
    """Split SQL into statements: [(line it starts on, text with comments/strings blanked)]."""
    clean = blank_comments_and_strings(code, "sql")
    return [(_line_of(clean, a), clean[a:b].rstrip(";").strip()) for a, b in sql_spans(code)]


def line_of(text: str, index: int) -> int:
    return _line_of(text, index)


def _sql(code: str, lines: list[str], rules: dict) -> list[dict]:
    found = []
    for line, text in sql_statements(code):
        upper = " ".join(text.upper().split())
        if re.match(r"^DELETE\s+FROM\b", upper) and " WHERE " not in f" {upper} ":
            found.append(finding(line, "critical", "bug", "This DELETE has no WHERE, so it deletes every row in the table.",
                                 "Add a WHERE condition, e.g. `DELETE FROM emp WHERE empno = 7369;`."))
        if re.match(r"^UPDATE\b", upper) and " WHERE " not in f" {upper} ":
            found.append(finding(line, "critical", "bug", "This UPDATE has no WHERE, so it changes every row in the table.",
                                 "Add a WHERE condition that picks only the rows to change."))
        if re.search(r"\bSELECT\s+(DISTINCT\s+)?\*", upper):
            found.append(finding(line, "suggestion", "performance", "`SELECT *` reads every column, even ones you don't need.",
                                 "List only the columns you need, e.g. `SELECT empno, ename, sal`."))
        if re.search(r"\bNOT\s+IN\s*\(\s*SELECT\b", upper):
            found.append(finding(line, "suggestion", "bug", "`NOT IN (SELECT ...)` returns no rows at all if the sub-query has a NULL.",
                                 "Use `NOT EXISTS (SELECT 1 FROM ... WHERE ...)` instead."))
        if re.search(r"\bFROM\s+\w+(\s+\w+)?\s*,\s*\w+", upper) and " JOIN " not in upper:
            found.append(finding(line, "suggestion", "readability", "Tables are joined with commas, which makes it easy to forget the join condition.",
                                 "Use `JOIN ... ON ...`, e.g. `FROM emp e JOIN dept d ON e.deptno = d.deptno`."))
        where = re.search(r"\bWHERE\b(.*)", upper)
        if where and re.search(r"\b(UPPER|LOWER|TO_CHAR|TRUNC|SUBSTR|YEAR|DATE)\s*\(\s*\w+(\.\w+)?\s*[,)]", where.group(1)):
            found.append(finding(line, "suggestion", "performance",
                                 "A function is used on a column in WHERE, so the database can't use an index on that column.",
                                 "Compare the column directly, e.g. `hiredate >= DATE '1981-01-01' AND hiredate < DATE '1982-01-01'`."))
        if re.search(r"\bLIKE\s+'\s*%", " ".join(code.split("\n")[line - 1:line + text.count("\n")]).upper()):
            found.append(finding(line, "suggestion", "performance", "`LIKE '%...'` (starting with %) can't use an index and reads the whole table.",
                                 "Search from the start of the text if you can (`LIKE 'abc%'`), or use full-text search."))
        if rules.get("no_print") and re.search(r"\bDBMS_OUTPUT\.PUT_LINE\b|^PRINT\b", upper):
            found.append(finding(line, "suggestion", "rule", "Printing output isn't allowed by the company rules.",
                                 "Remove the PRINT / DBMS_OUTPUT line.", "company"))
    return found


# ---------- Every language ----------
def _general(lines: list[str], language: str, rules: dict) -> list[dict]:
    found = []
    limit = int(rules.get("max_line_length") or 0)
    long_lines = [no for no, text in enumerate(lines, start=1) if limit and len(text) > limit]
    if long_lines:
        where = ", ".join(map(str, long_lines[:6])) + (f" and {len(long_lines) - 6} more" if len(long_lines) > 6 else "")
        found.append(finding(long_lines[0], "suggestion", "rule",
                             f"{len(long_lines)} line(s) are longer than the company limit of {limit} characters (lines {where}).",
                             "Break long lines into shorter ones.", "company"))
    comment = "--" if language == "sql" else "#" if language == "python" else "//"
    for no, text in enumerate(lines, start=1):
        if re.search(rf"({re.escape(comment)}|/\*|\*)\s*(TODO|FIXME|HACK|XXX)\b", text):
            found.append(finding(no, "suggestion", "readability", "There's an unfinished TODO/FIXME note here.",
                                 "Finish the work or create a ticket for it, then remove the note."))
    indents = [len(t) - len(t.lstrip()) for t in lines if t.strip()]
    step = min([i for i in indents if i > 0], default=4)
    deepest = max(indents, default=0) // max(step, 1)
    if deepest > 5 and language != "sql":
        line = next(no for no, t in enumerate(lines, start=1) if t.strip() and (len(t) - len(t.lstrip())) // step == deepest)
        found.append(finding(line, "suggestion", "readability", f"The code is nested {deepest} levels deep here, which is hard to follow.",
                             "Return early or move the inner part into its own function."))
    return found


def rule_checks(code: str, language: str, rules: dict | None = None) -> list[dict]:
    """All rule checks for one piece of code."""
    rules = {**DEFAULT_RULES, **(rules or {})}
    lines = code.split("\n")
    if language == "python":
        found = _python(code, lines, rules)
    elif language in ("javascript", "java"):
        found = _c_like(code, lines, language, rules)
    elif language == "sql":
        found = _sql(code, lines, rules)
    else:
        found = []
    return found + _general(lines, language, rules)
