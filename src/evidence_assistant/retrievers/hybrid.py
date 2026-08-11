from __future__ import annotations

import json
from pathlib import Path
from typing import List

from ..schemas import Chunk, Document
from ..text_utils import bm25_scores, cosine_scores, ranked_indices, rrf_fuse, split_text


def document_to_chunks(document: Document, max_chars: int = 900) -> List[Chunk]:
    parts = split_text(document.abstract, max_chars=max_chars)
    return [
        Chunk(
            id=f"{document.id}:chunk:{index}",
            doc_id=document.id,
            source=document.source,
            title=document.title,
            text=part,
            evidence_level=document.evidence_level,
            url=document.url,
            journal=document.journal,
            year=document.year,
            study_type=document.study_type,
            status=document.status,
            topic=document.topic,
        )
        for index, part in enumerate(parts, start=1)
    ]


class LocalCorpus:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.documents = self._load()
        self.chunks = [chunk for document in self.documents for chunk in document_to_chunks(document)]

    def _load(self) -> List[Document]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as handle:
            records = json.load(handle)
        return [Document(**record, retrieved_at="offline-snapshot") for record in records]

    @property
    def size(self) -> int:
        return len(self.documents)

    def search(self, terms: List[str], top_k: int = 12) -> List[Chunk]:
        if not self.chunks:
            return []
        query = " ".join(terms)
        searchable = [f"{chunk.title} {chunk.topic} {chunk.text}" for chunk in self.chunks]
        bm25 = bm25_scores(query, searchable)
        semantic = cosine_scores(query, searchable)
        rankings = [
            ranked_indices(bm25, min(100, len(searchable))),
            ranked_indices(semantic, min(100, len(searchable))),
        ]
        fused = rrf_fuse(rankings)
        ordered = sorted(fused, key=lambda index: (fused[index], max(bm25[index], semantic[index])), reverse=True)
        result: List[Chunk] = []
        for index in ordered[:top_k]:
            chunk = Chunk(**{**self.chunks[index].__dict__})
            chunk.retrieval_score = 0.55 * fused[index] + 0.25 * bm25[index] + 0.20 * semantic[index]
            result.append(chunk)
        return result
