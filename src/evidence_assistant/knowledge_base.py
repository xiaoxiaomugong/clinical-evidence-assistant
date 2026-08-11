from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Sequence

from .schemas import Chunk, SourceCitation
from .text_utils import bm25_scores, cosine_scores, ranked_indices, rrf_fuse


class KnowledgeBase:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self._chunks: List[Chunk] = []
        self._search_hints: List[str] = []
        self._pages: Dict[str, dict] = {}
        self.reload()

    def reload(self) -> None:
        self._chunks = []
        self._search_hints = []
        self._pages = {}
        for path in sorted(self.directory.glob("*.json")):
            with path.open("r", encoding="utf-8") as handle:
                page = json.load(handle)
            self._pages[page["id"]] = page
            keywords = " ".join(page.get("keywords", []))
            for claim in page.get("claims", []):
                citations = [SourceCitation(**citation) for citation in claim.get("citations", [])]
                context = " ".join(
                    part for part in [
                        claim["text"],
                        f"适用人群：{claim.get('applicable', '')}" if claim.get("applicable") else "",
                        f"例外：{claim.get('exceptions', '')}" if claim.get("exceptions") else "",
                    ] if part
                )
                self._chunks.append(
                    Chunk(
                        id=claim.get("id", f"{page['id']}:{len(self._chunks)}"),
                        doc_id=page["id"],
                        source="knowledge_page",
                        title=page["title"],
                        text=context,
                        evidence_level=claim["evidence_level"],
                        url=citations[0].url if citations else "",
                        topic=page.get("topic", ""),
                        citations=citations,
                    )
                )
                self._search_hints.append(keywords)

    @property
    def size(self) -> int:
        return len(self._chunks)

    @property
    def page_count(self) -> int:
        return len(self._pages)

    def page(self, page_id: str) -> dict:
        return self._pages[page_id]

    def all_pages(self) -> Sequence[dict]:
        return tuple(self._pages.values())

    def all_chunks(self) -> Sequence[Chunk]:
        return tuple(Chunk(**{**chunk.__dict__}) for chunk in self._chunks)

    def search(self, terms: List[str], top_k: int = 8) -> List[Chunk]:
        query = " ".join(terms)
        searchable = [
            f"{chunk.title} {chunk.topic} {hint} {chunk.text}"
            for chunk, hint in zip(self._chunks, self._search_hints)
        ]
        bm25 = bm25_scores(query, searchable)
        semantic = cosine_scores(query, searchable)
        bm25_rank = ranked_indices(bm25, min(100, len(searchable)))
        semantic_rank = ranked_indices(semantic, min(100, len(searchable)))
        fused = rrf_fuse([bm25_rank, semantic_rank])
        ordered = sorted(fused, key=lambda index: (fused[index], max(bm25[index], semantic[index])), reverse=True)
        result = []
        for index in ordered[:top_k]:
            chunk = Chunk(**{**self._chunks[index].__dict__})
            chunk.retrieval_score = 0.55 * fused[index] + 0.25 * bm25[index] + 0.20 * semantic[index]
            result.append(chunk)
        return result
