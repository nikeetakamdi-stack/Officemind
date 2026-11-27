"""All OfficeMind settings in one place, so they are easy to find and change."""

import os
from pathlib import Path

# Folders. For testing, the OFFICEMIND_DATA environment variable can point all data
# (databases and uploaded files) to another folder, so real data is never touched.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("OFFICEMIND_DATA", PROJECT_ROOT / "data"))
CHROMA_DIR = DATA_DIR / "chroma"  # ChromaDB saves its database files here
UPLOADS_DIR = DATA_DIR / "uploads"  # a copy of each uploaded PDF, so people can open it

# SQLite file with user accounts, helpdesk tickets and onboarding checklists.
DATABASE_PATH = Path(os.environ.get("OFFICEMIND_DB", DATA_DIR / "officemind.db"))

# Onboarding: an employee counts as "stuck" after this many days without ticking a task
ONBOARDING_STUCK_DAYS = 3

# ---------- Security ----------
DEPARTMENTS = ["General", "HR", "IT", "Finance", "Sales", "Operations"]
PASSWORD_MIN_LENGTH = 10       # plus at least one letter, one number and one symbol
LOCKOUT_ATTEMPTS = 5           # wrong passwords in a row before the account is locked
LOCKOUT_MINUTES = 15
IDLE_TIMEOUT_MINUTES = 30      # automatic sign-out after this long without activity
# The encryption key lives in this file (or in the OFFICEMIND_KEY environment variable).
# Back it up: without it, encrypted data can't be read.
SECRET_KEY_PATH = DATA_DIR / "secret.key"
PHONE_MIN_CONFIDENCE = 0.45    # Secure mode: how sure YOLO must be that it sees a phone
YOLO_MODEL_PATH = PROJECT_ROOT / "models" / "yolov8n.onnx"
# ---------- Team Chat ----------
CHAT_FILES_DIR = DATA_DIR / "chat_files"   # attachments, stored encrypted
CHAT_MAX_FILE_MB = 10
CHAT_REFRESH_SECONDS = 3                   # how often an open chat checks for new messages
ONLINE_SECONDS = 90                        # "online" = active in the last 90 seconds
# Calls use Jitsi Meet. meet.jit.si is the free public server; a company can run its own
# Jitsi server and put its address here, so calls never leave the company network.
JITSI_DOMAIN = os.environ.get("OFFICEMIND_JITSI", "meet.jit.si")

# Alerts
FAILED_LOGIN_ALERT = 3         # failed logins for one username within 15 minutes
CONFIDENTIAL_PROBE_ALERT = 3   # questions touching confidential documents within 24 hours

# Helpdesk settings
TICKET_CATEGORIES = ["Network", "Software", "Hardware", "Access", "Other"]

# Helpdesk AI: how alike two tickets must be (0 = unrelated, 1 = identical).
# Measured with nomic-embed-text: same problem ~0.71-0.77, different problems <= 0.66.
SIMILAR_TICKET_MIN = 0.70  # show "Similar issue already reported" at or above this
SOLVED_TICKET_MIN = 0.62  # past solved tickets the AI may learn a fix from
FIX_DOCUMENT_MAX_DISTANCE = 0.5  # document pieces the AI may use (smaller = closer match)

# Ollama models (both free and run on your own computer)
OLLAMA_CHAT_MODEL = "llama3.2"  # writes the answers
OLLAMA_EMBED_MODEL = "nomic-embed-text"  # turns text into numbers for searching

# Knowledge Assistant settings
KNOWLEDGE_COLLECTION = "knowledge_base"  # name of the ChromaDB "table"
CHUNK_SIZE = 1000  # characters per piece of text
CHUNK_OVERLAP = 200  # characters shared between neighbouring pieces
TOP_K = 4  # how many pieces to give the AI for each question
SOURCE_MARGIN = 0.1  # show a source only if it matched almost as well as the best one

# ---------- Code Review ----------
CODE_LANGUAGES = {"python": "Python", "javascript": "JavaScript", "java": "Java", "sql": "SQL"}
CODE_EXTENSIONS = {".py": "python", ".js": "javascript", ".java": "java", ".sql": "sql"}
CODE_MAX_KB = 200          # biggest file you can paste or upload
CODE_AI_MAX_LINES = 400    # the AI reads at most this many lines (rule checks read everything)
