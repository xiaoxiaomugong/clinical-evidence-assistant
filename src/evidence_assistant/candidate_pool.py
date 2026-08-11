from __future__ import annotations

from typing import Dict, Iterable, List

from .retrievers.hybrid import document_to_chunks
from .schemas import Chunk, Document, Entry


def _entry_from_chunk(chunk: Chunk) -> Entry:
    return Entry(**chunk.__dict__)


def build(
    docs: Iterable[Document] = (),
    chunks: Iterable[Chunk] = (),
    pages: Iterable[Chunk] = (),
) -> List[Entry]:
    all_chunks = list(chunks) + list(pages)
    for document in docs:
        all_chunks.extend(document_to_chunks(document))

    deduped: Dict[str, Entry] = {}
    text_seen = set()
    for chunk in all_chunks:
        text_key = " ".join(chunk.text.lower().split())[:600]
        if text_key in text_seen:
            continue
        text_seen.add(text_key)
        entry = _entry_from_chunk(chunk)
        current = deduped.get(entry.id)
        if current is None or entry.retrieval_score > current.retrieval_score:
            deduped[entry.id] = entry
    return list(deduped.values())
