"""The helpdesk AI (Ollama llama3.2 + nomic-embed-text).

When an employee describes a problem, analyze_ticket():
1. suggests a category and an urgency,
2. finds open tickets about the same problem ("Similar issue already reported"),
3. suggests a possible fix, using past closed tickets with admin replies and the uploaded documents.
"""

import math

from core.config import (
    FIX_DOCUMENT_MAX_DISTANCE,
    SIMILAR_TICKET_MIN,
    SOLVED_TICKET_MIN,
    TICKET_CATEGORIES,
)
from core.llm import chat_json, embed
from modules.helpdesk.tickets import URGENCIES, active_tickets, solved_tickets
from modules.knowledge.assistant import search_documents

# nomic-embed-text compares best when the new text is a "query" and the old ones are "documents"
QUERY_PREFIX = "search_query: "
DOCUMENT_PREFIX = "search_document: "

LABEL_PROMPT = """You are an IT helpdesk assistant. Read a ticket and choose its category and urgency.

Categories:
- Network: internet, Wi-Fi, VPN, slow or no connection.
- Software: a program or app crashes, shows errors, won't install or update.
- Hardware: physical devices: laptop, monitor, mouse, keyboard, printer, phone, cables.
- Access: accounts, passwords, logins, permissions, licences, access to folders or apps.
- Other: anything else.

Urgency:
- high: the person cannot work at all (no internet, can't log in, laptop won't start),
  several people are affected, or there is a security or data-loss risk.
- medium: the person can still work but is slowed down, or one app is broken.
- low: a small annoyance, a cosmetic problem, or a request that can wait.

Reply with JSON only, like {"category": "Network", "urgency": "high"}."""

# The AI only rewrites fixes that the search already found, so it can't invent a fix
# for an unrelated problem. (Tested: when asked to judge relevance itself, llama3.2 was
# inconsistent and added its own steps; this smaller job gives steady, faithful answers.)
FIX_PROMPT = """Rewrite the KNOWN FIXES below as clear steps for an office employee.
Rules: use only the actions written in the known fixes; do not add any other action.
Use as few steps as needed - one step is fine. At most 3.
Reply with JSON only: {"steps": ["...", "..."]}"""

SNIPPET_LENGTH = 280  # characters of a document piece shown as evidence


def _similarity(a: list[float], b: list[float]) -> float:
    """How alike two embeddings are: 1 = same meaning, 0 = unrelated."""
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def _ticket_text(ticket: dict) -> str:
    return f"{ticket['title']}. {ticket['description']}"


def suggest_labels(title: str, description: str) -> tuple[str, str]:
    """Ask llama3.2 for (category, urgency). Falls back to ("Other", "medium") if unsure."""
    data = chat_json(LABEL_PROMPT, f"Title: {title}\nDescription: {description}")
    category = str(data.get("category", "")).strip().title()
    urgency = str(data.get("urgency", "")).strip().lower()
    if category not in TICKET_CATEGORIES:
        category = "Other"
    if urgency not in URGENCIES:
        urgency = "medium"
    return category, urgency


def find_similar_open(new_vector: list[float], limit: int = 3) -> list[dict]:
    """Open / In Progress tickets about the same problem, most alike first."""
    tickets = active_tickets()
    if not tickets:
        return []
    vectors = embed([DOCUMENT_PREFIX + _ticket_text(t) for t in tickets])
    scored = [(_similarity(new_vector, v), t) for t, v in zip(tickets, vectors)]
    matches = [
        {**t, "score": round(score, 2)}
        for score, t in sorted(scored, key=lambda pair: pair[0], reverse=True)
        if score >= SIMILAR_TICKET_MIN
    ]
    return matches[:limit]


def suggest_fix(title: str, description: str, new_vector: list[float]) -> dict | None:
    """A possible fix, based only on past solved tickets and the uploaded documents.

    Returns None if nothing relevant was found, otherwise
    {"steps": [...], "evidence": [{"label": "Ticket #4 · WiFi not working", "text": "..."}, ...]}.
    "evidence" is the original text the steps come from, so people can check them."""
    # 1. Past closed tickets with admin replies that look like this problem
    solved = solved_tickets()
    past = []
    if solved:
        vectors = embed([DOCUMENT_PREFIX + _ticket_text(t) for t in solved])
        scored = sorted(
            ((_similarity(new_vector, v), t) for t, v in zip(solved, vectors)),
            key=lambda pair: pair[0],
            reverse=True,
        )
        past = [t for score, t in scored if score >= SOLVED_TICKET_MIN][:3]

    # 2. Pieces of the uploaded documents that look like this problem
    pieces = [
        p for p in search_documents(f"{title}. {description}", limit=3)
        if p["distance"] <= FIX_DOCUMENT_MAX_DISTANCE
    ]

    if not past and not pieces:
        return None  # nothing relevant to learn from, so don't guess

    evidence = [
        {"label": f"Ticket #{t['id']} · {t['title']}", "text": t["solution"]} for t in past
    ]
    for p in pieces:
        snippet = p["text"][:SNIPPET_LENGTH] + ("…" if len(p["text"]) > SNIPPET_LENGTH else "")
        evidence.append({"label": f"{p['source']} · page {p['page']}", "text": snippet})

    # 3. Let the AI turn those fixes into simple steps
    known_fixes = "\n".join(f"- {t['solution']}" for t in past)
    known_fixes += "".join(f"\n- {p['text']}" for p in pieces)
    data = chat_json(FIX_PROMPT, f"KNOWN FIXES:\n{known_fixes}")
    steps = [str(step).strip() for step in data.get("steps", []) if str(step).strip()][:3]

    return {"steps": steps, "evidence": evidence}


def analyze_ticket(title: str, description: str) -> dict:
    """Run all three AI checks. Each part that fails is simply left out, so the
    employee can always still submit the ticket."""
    result = {
        "category": "Other",
        "urgency": "medium",
        "similar": [],
        "fix": None,
        "problems": [],
    }
    try:
        result["category"], result["urgency"] = suggest_labels(title, description)
    except Exception as error:
        result["problems"].append(f"Couldn't suggest a category/urgency ({error}).")

    try:
        new_vector = embed([QUERY_PREFIX + f"{title}. {description}"])[0]
    except Exception as error:
        result["problems"].append(f"Couldn't search old tickets ({error}).")
        return result

    try:
        result["similar"] = find_similar_open(new_vector)
    except Exception as error:
        result["problems"].append(f"Couldn't check for similar tickets ({error}).")

    try:
        result["fix"] = suggest_fix(title, description, new_vector)
    except Exception as error:
        result["problems"].append(f"Couldn't suggest a fix ({error}).")

    return result
