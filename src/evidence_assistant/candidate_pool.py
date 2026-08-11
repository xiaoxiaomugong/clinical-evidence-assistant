from __future__ import annotations

import re
from collections import defaultdict
from typing import Dict, Iterable, List

from .retrievers.hybrid import document_to_chunks
from .schemas import Chunk, Document, Entry


def _entry_from_chunk(chunk: Chunk) -> Entry:
    return Entry(**chunk.__dict__)


def canonical_source_id(item) -> str:
    """Return a cross-provider identity for independent-source counting and dedup."""
    for citation in getattr(item, "citations", []) or []:
        if citation.pmid:
            return f"pmid:{citation.pmid}"
        if citation.doi:
            return f"doi:{citation.doi.lower()}"
        if citation.nct_id:
            return f"nct:{citation.nct_id.upper()}"
        if citation.chapter:
            return f"chapter:{citation.chapter.lower()}"

    joined = " ".join(
        str(value or "")
        for value in (getattr(item, "doc_id", ""), getattr(item, "id", ""), getattr(item, "url", ""))
    )
    pmid = re.search(r"(?:pmid[:/]|pubmed\.ncbi\.nlm\.nih\.gov/)(\d{5,9})", joined, re.IGNORECASE)
    if pmid:
        return f"pmid:{pmid.group(1)}"
    nct = re.search(r"\b(NCT\d{8})\b", joined, re.IGNORECASE)
    if nct:
        return f"nct:{nct.group(1).upper()}"
    doi = re.search(r"\b(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", joined, re.IGNORECASE)
    if doi:
        return f"doi:{doi.group(1).rstrip('.,)').lower()}"
    return str(getattr(item, "doc_id", "") or getattr(item, "id", "")).lower()


def research_family_id(item) -> str:
    """Group multiple publications/chunks from the same registered research family."""
    for citation in getattr(item, "citations", []) or []:
        if citation.nct_id:
            return f"trial:{citation.nct_id.upper()}"
    joined = " ".join(
        str(value or "")
        for value in (getattr(item, "doc_id", ""), getattr(item, "id", ""), getattr(item, "url", ""))
    )
    nct = re.search(r"\b(NCT\d{8})\b", joined, re.IGNORECASE)
    if nct:
        return f"trial:{nct.group(1).upper()}"
    return canonical_source_id(item)


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

    grouped = defaultdict(list)
    for entry in deduped.values():
        grouped[research_family_id(entry)].append(entry)
    result: List[Entry] = []
    for entries in grouped.values():
        entries.sort(
            key=lambda item: (
                item.source == "knowledge_page",
                item.retrieval_score,
                len(item.text),
            ),
            reverse=True,
        )
        result.extend(entries[:2])
    return result
