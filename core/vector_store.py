"""Opens the ChromaDB database. Each module keeps its data in its own collection."""

import chromadb

from core.config import CHROMA_DIR

_client = None


def get_collection(name: str):
    """Return a ChromaDB collection, creating it the first time it is used."""
    global _client
    if _client is None:
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return _client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},  # compare texts by meaning
    )
