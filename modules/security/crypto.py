"""Encryption for sensitive data stored in the database (ticket text, replies,
AI questions, activity details, email addresses).

Uses Fernet (AES-128 in CBC mode with an HMAC signature) from the `cryptography`
package. The key is read from the OFFICEMIND_KEY environment variable, or from
data/secret.key, which is created the first time it's needed. That file is never
uploaded to GitHub (*.key is in .gitignore). Keep a backup of it: without the key,
encrypted data can't be read.

Encrypted values are saved as "enc:v1:<token>". Anything without that prefix is
treated as old plain text, so data from before this feature still works.
"""

import os

from cryptography.fernet import Fernet, InvalidToken

from core.config import SECRET_KEY_PATH

PREFIX = "enc:v1:"
_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = os.environ.get("OFFICEMIND_KEY")
        if not key:
            if not SECRET_KEY_PATH.exists():
                SECRET_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
                SECRET_KEY_PATH.write_bytes(Fernet.generate_key())
            key = SECRET_KEY_PATH.read_bytes().strip()
        _fernet = Fernet(key)
    return _fernet


def encrypt(text: str | None) -> str | None:
    """Scramble text so it can only be read with the key. None stays None."""
    if text is None or text.startswith(PREFIX):
        return text
    return PREFIX + _get_fernet().encrypt(text.encode("utf-8")).decode("ascii")


def decrypt(value: str | None) -> str | None:
    """Turn an encrypted value back into text. Plain (old) text is returned as it is."""
    if value is None or not value.startswith(PREFIX):
        return value
    try:
        return _get_fernet().decrypt(value[len(PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken:
        return "[cannot be decrypted: wrong key]"


def is_encrypted(value: str | None) -> bool:
    return bool(value) and value.startswith(PREFIX)
