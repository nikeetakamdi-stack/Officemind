"""All OfficeMind settings in one place, so they are easy to find and change."""

from pathlib import Path

# Folders
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CHROMA_DIR = DATA_DIR / "chroma"  # ChromaDB saves its database files here
DATABASE_PATH = DATA_DIR / "officemind.db"  # SQLite file with user accounts

# Ollama models (both free and run on your own computer)
OLLAMA_CHAT_MODEL = "llama3.2"  # writes the answers
OLLAMA_EMBED_MODEL = "nomic-embed-text"  # turns text into numbers for searching

# Knowledge Assistant settings
KNOWLEDGE_COLLECTION = "knowledge_base"  # name of the ChromaDB "table"
CHUNK_SIZE = 1000  # characters per piece of text
CHUNK_OVERLAP = 200  # characters shared between neighbouring pieces
TOP_K = 4  # how many pieces to give the AI for each question
SOURCE_MARGIN = 0.1  # show a source only if it matched almost as well as the best one
