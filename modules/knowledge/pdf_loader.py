"""Reads text out of PDF files and cuts it into small pieces ("chunks")."""

from pypdf import PdfReader


def read_pdf_pages(file) -> list[tuple[int, str]]:
    """Return a list of (page number, page text), skipping empty pages."""
    reader = PdfReader(file)
    pages = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        text = " ".join(text.split())  # tidy up extra spaces and line breaks
        if text:
            pages.append((page_number, text))
    return pages


def split_into_chunks(text: str, size: int, overlap: int) -> list[str]:
    """Cut text into pieces of `size` characters that overlap a little,
    so a sentence cut in half still appears whole in one of the pieces."""
    chunks = []
    start = 0
    while True:
        end = start + size
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap
    return chunks
