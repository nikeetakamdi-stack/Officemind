"""Check code the AI wrote (improved, commented or converted code) before showing it.

These checks can't prove the code is right, but they catch the usual mistakes of a
small model: code that doesn't run, names that were never defined, functions that
went missing, extra "example usage" code, and SQL clauses in the wrong order.
"""

import ast
import builtins
import re

from modules.codereview.checks import blank_comments_and_strings, sql_statements

BUILTIN_NAMES = set(dir(builtins)) | {"__name__", "__file__", "__doc__", "self", "cls"}


def python_problems(code: str) -> list[str]:
    """Problems that mean this Python code can't work as written."""
    try:
        tree = ast.parse(code)
    except SyntaxError as error:
        return [f"It isn't valid Python (line {error.lineno}: {error.msg})."]
    module_names = set(BUILTIN_NAMES)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            module_names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            module_names.update((a.asname or a.name).split(".")[0] for a in node.names)
    for node in ast.walk(tree):  # names stored at module level (incl. for loops, with, etc.)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            module_names.add(node.id)
    problems = []
    for func in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        local = {a.arg for a in func.args.args + func.args.kwonlyargs + func.args.posonlyargs}
        local |= {a.arg for a in (func.args.vararg, func.args.kwarg) if a}
        for node in ast.walk(func):
            if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                local.add(node.id)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                local.add(node.name)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                local.update((a.asname or a.name).split(".")[0] for a in node.names)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                local.add(node.name)
            elif isinstance(node, (ast.Global, ast.Nonlocal)):
                local.update(node.names)
        missing = sorted({n.id for n in ast.walk(func) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
                          and n.id not in local and n.id not in module_names})
        for name in missing:
            problems.append(f"`{func.name}` uses `{name}`, which isn't defined anywhere.")
    return problems


def _functions(code: str, language: str) -> set[str]:
    if language == "python":
        try:
            return {n.name for n in ast.walk(ast.parse(code)) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        except SyntaxError:
            return set()
    clean = blank_comments_and_strings(code, language)
    if language == "javascript":
        return {a or b for a, b in re.findall(r"\bfunction\s+(\w+)|\b(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(", clean)}
    if language == "java":
        return set(re.findall(r"\b(?:public|private|protected|static)[\w\s<>\[\],]*?\s(\w+)\s*\([^;{]*\)\s*(?:throws[\w\s,.]+)?\{", clean))
    return set()


def sql_problems(code: str) -> list[str]:
    """SQL clauses in an impossible order (e.g. JOIN after WHERE, two WHEREs)."""
    order = ["SELECT", "FROM", "JOIN", "WHERE", "GROUP BY", "HAVING", "ORDER BY"]
    problems = []
    for line, text in sql_statements(code):
        flat, depth = [], 0
        for ch in text.upper():  # only look at the top level, not inside ( sub-queries )
            depth += ch == "("
            flat.append(ch if depth == 0 else " ")
            depth -= ch == ")"
        top = " ".join("".join(flat).split())
        if not top.startswith(("SELECT", "WITH")):
            continue
        found = [(m.start(), m.group(1)) for m in re.finditer(r"\b(SELECT|FROM|(?:\w+ )?JOIN|WHERE|GROUP BY|HAVING|ORDER BY)\b", top)]
        names = ["JOIN" if k.endswith("JOIN") else k for _, k in found]
        if names.count("WHERE") > 1 or names.count("FROM") > 1:
            problems.append(f"The statement on line {line} has two WHERE or FROM parts.")
            continue
        ranks = [order.index(k) for k in names if k in order]
        if any(b < a for a, b in zip(ranks, ranks[1:])) and not "UNION" in top:
            problems.append(f"The statement on line {line} has its parts in the wrong order (e.g. JOIN after WHERE).")
    return problems


def rewrite_problems(original: str, new: str, language: str, keep_functions: bool = True,
                     same_language: bool = True, renames: dict | None = None) -> list[str]:
    """Everything wrong with AI-written code, in plain words (empty list = passed the checks)."""
    if not new.strip():
        return ["The AI didn't return any code."]
    problems = []
    if language == "python":
        problems += python_problems(new)
    elif language == "sql":
        problems += sql_problems(new)
    elif new.count("{") != new.count("}"):
        problems.append("The { and } brackets don't match, so the code won't compile.")
    if same_language and keep_functions:
        now = _functions(new, language)
        lost = sorted(n for n in _functions(original, language) - now if (renames or {}).get(n) not in now)
        if lost:
            problems.append("These functions went missing: " + ", ".join(f"`{n}`" for n in lost) + ".")
        if re.search(r"(#|//|--)\s*example usage", new, re.IGNORECASE) and not re.search(r"example usage", original, re.IGNORECASE):
            problems.append("It added example code that wasn't in the original.")
    return problems
