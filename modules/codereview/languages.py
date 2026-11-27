"""Work out which programming language some code is written in.

From the file name when there is one (.py, .js, .java, .sql), otherwise by looking
for words and shapes that only appear in one language (a simple points system).
"""

import ast
import re
from pathlib import Path

from core.config import CODE_EXTENSIONS, CODE_LANGUAGES

# (pattern, points) for each language
HINTS = {
    "python": [
        (r"^\s*def \w+\(.*\)\s*(->.*)?:\s*$", 3), (r"^\s*(from [\w.]+ )?import [\w., ]+$", 2),
        (r"^\s*(if|elif|for|while|with|try|else|except.*)\b.*:\s*$", 1), (r"\bprint\(", 1),
        (r"\bself\b", 1), (r"^\s*class \w+(\(.*\))?:\s*$", 3), (r"\bNone\b|\bTrue\b|\bFalse\b", 1),
    ],
    "javascript": [
        (r"\bfunction\s*\w*\s*\(", 2), (r"\b(const|let|var)\s+\w+\s*=", 2), (r"=>", 2),
        (r"\bconsole\.\w+\(", 3), (r"\brequire\(['\"]", 3), (r"\bdocument\.|\bwindow\.", 3),
        (r"===|!==", 2), (r"\bexport (default|const|function)\b", 3),
    ],
    "java": [
        (r"\bpublic\s+(static\s+)?(class|void|int|String)\b", 3), (r"\bSystem\.out\.print", 4),
        (r"^\s*import java\.", 4), (r"\bprivate\s+\w+(<.*>)?\s+\w+\s*[;=]", 2),
        (r"\bString\[\]\s+args\b", 4), (r"\bnew\s+[A-Z]\w*(<.*>)?\(", 1), (r"@Override", 3),
    ],
    "sql": [
        (r"^\s*SELECT\b", 3), (r"\bFROM\s+\w+", 2), (r"^\s*(INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM)\b", 4),
        (r"^\s*CREATE\s+(TABLE|VIEW|INDEX|PROCEDURE)\b", 4), (r"\bGROUP\s+BY\b|\bORDER\s+BY\b", 2),
        (r"\bWHERE\b", 1), (r"\bJOIN\b.*\bON\b", 2),
    ],
}


def language_from_filename(filename: str | None) -> str | None:
    if not filename:
        return None
    return CODE_EXTENSIONS.get(Path(filename).suffix.lower())


def detect_language(code: str, filename: str | None = None) -> tuple[str, str]:
    """Returns (language, how it was decided), e.g. ("python", "from the file name")."""
    by_name = language_from_filename(filename)
    if by_name:
        return by_name, "from the file name"
    points = {}
    for language, hints in HINTS.items():
        flags = re.MULTILINE | (re.IGNORECASE if language == "sql" else 0)
        points[language] = sum(weight * len(re.findall(pattern, code, flags)) for pattern, weight in hints)
    try:
        ast.parse(code)
        points["python"] += 3  # it's valid Python
    except (SyntaxError, ValueError):
        pass
    best = max(points, key=points.get)
    if points[best] == 0:
        return "python", "guessed (no clear signs, please pick the language)"
    return best, "detected automatically"


def label(language: str) -> str:
    return CODE_LANGUAGES.get(language, language)
