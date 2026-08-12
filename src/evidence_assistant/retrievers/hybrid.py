from __future__ import annotations

import json
from pathlib import Path
from typing import List, Sequence

from ..interfaces import BackendStatus, Retriever
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
        documents = []
        for record in records:
            normalized = dict(record)
            normalized["retrieved_at"] = normalized.get("retrieved_at") or "offline-snapshot"
            documents.append(Document(**normalized))
        return documents

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


class PrecomputedRetriever:
    """Expose an already ranked source list through the common retriever protocol."""

    def __init__(self, chunks: Sequence[Chunk], backend_name: str = "legacy"):
        self.chunks = list(chunks)
        self.status = BackendStatus(requested=backend_name, actual=backend_name)

    def search(self, query_plan, top_k: int) -> List[Chunk]:
        del query_plan
        return [Chunk(**{**chunk.__dict__}) for chunk in self.chunks[:top_k]]


class HybridRetriever:
    """RRF-fuse independently ranked lexical sources and a dense source."""

    def __init__(self, retrievers: Sequence[Retriever], rrf_k: int = 60):
        self.retrievers = list(retrievers)
        self.rrf_k = rrf_k
        self.status = BackendStatus(requested="hybrid", actual="hybrid")

    def search(self, query_plan, top_k: int) -> List[Chunk]:
        rankings = [retriever.search(query_plan, top_k) for retriever in self.retrievers]
        chunks = {}
        fused = {}
        best_source_score = {}
        dense_available = False
        degradation_reasons = []

        for retriever, ranking in zip(self.retrievers, rankings):
            if retriever.status.actual == "dense" and not retriever.status.degraded:
                dense_available = True
            if retriever.status.degraded and retriever.status.reason:
                degradation_reasons.append(retriever.status.reason)
            for rank, chunk in enumerate(ranking, start=1):
                chunks[chunk.id] = chunk
                fused[chunk.id] = fused.get(chunk.id, 0.0) + 1.0 / (self.rrf_k + rank)
                best_source_score[chunk.id] = max(
                    best_source_score.get(chunk.id, 0.0), chunk.retrieval_score
                )

        maximum = max(fused.values(), default=0.0)
        ordered = sorted(
            chunks,
            key=lambda chunk_id: (fused[chunk_id], best_source_score[chunk_id]),
            reverse=True,
        )
        results: List[Chunk] = []
        per_document = {}
        for chunk_id in ordered:
            chunk = chunks[chunk_id]
            if per_document.get(chunk.doc_id, 0) >= 2:
                continue
            clone = Chunk(**{**chunk.__dict__})
            rrf_score = fused[chunk_id] / maximum if maximum else 0.0
            clone.retrieval_score = 0.70 * rrf_score + 0.30 * best_source_score[chunk_id]
            results.append(clone)
            per_document[chunk.doc_id] = per_document.get(chunk.doc_id, 0) + 1
            if len(results) >= top_k:
                break

        self.status = BackendStatus(
            requested="hybrid",
            actual="hybrid" if dense_available else "legacy",
            degraded=not dense_available,
            reason="; ".join(dict.fromkeys(degradation_reasons))[:500],
        )
        return results
