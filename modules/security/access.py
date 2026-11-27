"""Who may see which document.

Every document has an access level:
- Public:          everyone
- Department-only: people in the same department as the document (and admins)
- Confidential:    admins, and people an admin has given "confidential access"

The rule is applied *inside the search*, before the AI sees anything. So even if
someone tricks the AI, it can't reveal a document it never received.
"""

ACCESS_LEVELS = {
    "public": "Public",
    "department": "Department-only",
    "confidential": "Confidential",
}
ACCESS_ICONS = {"public": "public", "department": "groups", "confidential": "lock"}


def is_admin(user: dict | None) -> bool:
    return bool(user) and user.get("role") == "admin"


def can_see_confidential(user: dict | None) -> bool:
    return is_admin(user) or bool(user and user.get("clearance"))


def can_open(user: dict | None, access: str, department: str | None) -> bool:
    """May this user see a document with this access level and department?"""
    if is_admin(user):
        return True
    if not user:
        return False
    if access == "public":
        return True
    if access == "department":
        return bool(department) and department == user.get("department")
    if access == "confidential":
        return can_see_confidential(user)
    return False  # unknown level: say no


def search_filter(user: dict | None, include_confidential: bool = True) -> dict | None:
    """The ChromaDB "where" filter for this user. None means "no filter" (admins).

    Pieces of documents without an access level never match, so they stay hidden
    from employees until an admin gives them one."""
    if is_admin(user) and include_confidential:
        return None
    allowed = [{"access": "public"}]
    if user and user.get("department"):
        allowed.append({"$and": [{"access": "department"}, {"department": user["department"]}]})
    if include_confidential and can_see_confidential(user):
        allowed.append({"access": "confidential"})
    if is_admin(user):  # admin without confidential (Secure mode off): every department
        allowed.append({"access": "department"})
    return allowed[0] if len(allowed) == 1 else {"$or": allowed}
