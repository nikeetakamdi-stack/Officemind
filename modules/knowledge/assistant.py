"""The Knowledge Assistant's brain: save PDFs, then answer questions from them."""

from core.config import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    KNOWLEDGE_COLLECTION,
    SOURCE_MARGIN,
    TOP_K,
)
from core.llm import chat, embed
from core.vector_store import get_collection
from modules.knowledge.pdf_loader import read_pdf_pages, split_into_chunks

NOT_FOUND = "I couldn't find that in the uploaded documents."

SYSTEM_PROMPT = f"""You are OfficeMind, a helpful workplace assistant.
You are given excerpts from company documents as context.
If the context contains the answer, answer clearly in one or two sentences and say which file it came from.
Use only facts from the context, never outside knowledge.
If nothing in the context answers the question, reply exactly: {NOT_FOUND}"""

# The nomic-embed-text model searches better when texts start with these labels
DOCUMENT_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "


def add_pdf(file, filename: str) -> int:
    """Read a PDF, split it into chunks and save them in ChromaDB.
    Returns how many chunks were saved (0 means no text was found)."""
    ids, chunks, metadatas = [], [], []
    for page_number, page_text in read_pdf_pages(file):
        for i, chunk in enumerate(split_into_chunks(page_text, CHUNK_SIZE, CHUNK_OVERLAP)):
            ids.append(f"{filename}::page{page_number}::chunk{i}")
            chunks.append(chunk)
            metadatas.append({"source": filename, "page": page_number})

    if not chunks:
        return 0

    collection = get_collection(KNOWLEDGE_COLLECTION)
    # If this file was uploaded before, remove the old copy first
    collection.delete(where={"source": filename})
    embeddings = embed([DOCUMENT_PREFIX + chunk for chunk in chunks])
    collection.add(ids=ids, documents=chunks, embeddings=embeddings, metadatas=metadatas)
    return len(chunks)


def list_documents() -> list[str]:
    """Return the names of all files saved in the knowledge base."""
    collection = get_collection(KNOWLEDGE_COLLECTION)
    metadatas = collection.get(include=["metadatas"])["metadatas"]
    return sorted({m["source"] for m in metadatas})


def delete_document(filename: str) -> None:
    """Remove every chunk of this file from ChromaDB, so answers no longer use it."""
    collection = get_collection(KNOWLEDGE_COLLECTION)
    collection.delete(where={"source": filename})


def ask(question: str) -> tuple[str, list[dict]]:
    """Find the chunks most related to the question and let the AI answer from them.
    Returns (answer, sources), where each source is {"source": file, "page": number}."""
    collection = get_collection(KNOWLEDGE_COLLECTION)
    total = collection.count()
    if total == 0:
        return "No documents yet. Please upload a PDF first.", []

    results = collection.query(
        query_embeddings=embed([QUERY_PREFIX + question]),
        n_results=min(TOP_K, total),
    )
    chunks = results["documents"][0]
    metadatas = results["metadatas"][0]
    distances = results["distances"][0]  # smaller number = closer match

    context = "\n\n".join(
        f"[File: {m['source']}, page {m['page']}]\n{chunk}"
        for chunk, m in zip(chunks, metadatas)
    )
    answer = chat(SYSTEM_PROMPT, f"Context:\n{context}\n\nQuestion: {question}")

    if NOT_FOUND.lower() in answer.lower():
        return answer, []  # no answer, so no sources to show

    # Keep only pages that matched almost as well as the best one,
    # without duplicates, best match first
    best = distances[0]
    sources = []
    for m, distance in zip(metadatas, distances):
        item = {"source": m["source"], "page": m["page"]}
        if distance <= best + SOURCE_MARGIN and item not in sources:
            sources.append(item)
    return answer, sources
