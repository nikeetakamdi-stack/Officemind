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
