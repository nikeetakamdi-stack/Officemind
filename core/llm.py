"""Talks to Ollama. Every module in OfficeMind uses these functions."""

import json

import ollama

from core.config import OLLAMA_CHAT_MODEL, OLLAMA_EMBED_MODEL


def embed(texts: list[str]) -> list[list[float]]:
    """Turn each text into a list of numbers (an "embedding") for searching."""
    embeddings = []
    batch_size = 32  # send a few at a time so big PDFs don't overload Ollama
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        response = ollama.embed(model=OLLAMA_EMBED_MODEL, input=batch)
        embeddings.extend(response["embeddings"])
    return embeddings


def chat(system_prompt: str, user_prompt: str) -> str:
    """Send a prompt to the chat model and return its reply as text."""
    response = ollama.chat(
        model=OLLAMA_CHAT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        options={"temperature": 0},  # 0 = no creativity, same question gives same answer
    )
    return response["message"]["content"]


def chat_json(system_prompt: str, user_prompt: str) -> dict:
    """Like chat(), but the model must answer in JSON (data a program can read).
    Returns {} if the reply can't be read."""
    response = ollama.chat(
        model=OLLAMA_CHAT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        format="json",  # Ollama makes sure the reply is valid JSON
        options={"temperature": 0},
    )
    try:
        data = json.loads(response["message"]["content"])
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}
