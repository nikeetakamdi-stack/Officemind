"""Hide personal data in text shown on screen (AI answers, search snippets, evidence).

Found items are replaced with ****. The patterns are written for Indian formats:
- email addresses                       name@company.com
- PAN                                   ABCDE1234F
- Aadhaar (12 digits, first is 2-9)     2345 6789 0123
- phone numbers                         +91 98765 43210, 098765 43210, 9876543210
- bank account numbers (9-18 digits)    123456789012345

Order matters: longer, more specific patterns go first, so a 12-digit Aadhaar
isn't mistaken for a bank account.
"""

import re

MASK = "****"

PATTERNS = [
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b", re.IGNORECASE)),
    ("Aadhaar", re.compile(r"(?<!\d)[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}(?!\d)")),
    ("phone", re.compile(r"(?<![\w+])(?:\+91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")),
    ("bank account", re.compile(r"(?<!\d)\d{9,18}(?!\d)")),
]


def mask_sensitive(text: str) -> tuple[str, int]:
    """Returns (text with personal data replaced by ****, how many items were hidden)."""
    if not text:
        return text, 0
    total = 0
    for _, pattern in PATTERNS:
        text, count = pattern.subn(MASK, text)
        total += count
    return text, total


def mask(text: str) -> str:
    return mask_sensitive(text)[0]
