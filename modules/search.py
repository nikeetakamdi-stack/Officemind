"""The search box in the top bar: looks through pages, tickets, documents and onboarding tasks.

Everyone only finds what they're allowed to see (employees: their own tickets and tasks).
"""

from core.ui import NAV
from modules.helpdesk.tickets import STATUSES, list_tickets
from modules.onboarding.checklists import list_checklists, list_tasks, my_onboarding

PAGE_WORDS = {
    "app.py": "home start welcome overview",
    "pages/1_Knowledge_Assistant.py": "ask question ai assistant documents pdf policy upload knowledge",
    "pages/2_Helpdesk.py": "ticket it support problem help issue helpdesk",
    "pages/3_Onboarding.py": "onboarding checklist tasks new employee first week",
    "pages/4_Dashboard.py": "dashboard stats charts report excel export manager",
}


def _matches(query: str, *texts: str) -> bool:
    """True if every word of the query appears somewhere in the texts."""
    haystack = " ".join(t or "" for t in texts).lower()
    return all(word in haystack for word in query.lower().split())


def search(user: dict, query: str) -> dict:
    """Returns {"pages": [...], "tickets": [...], "documents": [...], "passages": [...], "tasks": [...]}."""
    admin = user["role"] == "admin"
    results = {"pages": [], "tickets": [], "documents": [], "passages": [], "tasks": []}

    for page, label, icon_name, admin_only in NAV:
        if (not admin_only or admin) and _matches(query, label, PAGE_WORDS.get(page, "")):
            results["pages"].append({"page": page, "label": label, "icon": icon_name})

    for ticket in list_tickets(user):  # employees only get their own
        if _matches(query, ticket["title"], ticket["description"], ticket["category"], f"#{ticket['id']}"):
            results["tickets"].append({**ticket, "status_label": STATUSES[ticket["status"]]})

    if admin:
        for checklist in list_checklists():
            for task in list_tasks(checklist["id"]):
                if _matches(query, task["title"], task["description"], checklist["name"]):
                    results["tasks"].append({**task, "checklist": checklist["name"], "done": None})
    else:
        for assignment in my_onboarding(user):
            for task in assignment["tasks"]:
                if _matches(query, task["title"], task["description"], assignment["name"]):
                    results["tasks"].append({**task, "checklist": assignment["name"]})

    # Documents: names that match, plus the passages closest in meaning (needs Ollama)
    try:
        from modules.knowledge.assistant import list_documents, search_documents

        results["documents"] = [name for name in list_documents() if _matches(query, name)]
        results["passages"] = [p for p in search_documents(query, limit=3) if p["distance"] <= 0.5]
        results["ai_ok"] = True
    except Exception:
        results["ai_ok"] = False
    return results
