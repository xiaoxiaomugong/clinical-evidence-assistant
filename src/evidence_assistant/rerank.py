from __future__ import annotations

from typing import List

from .schemas import Entry
from .text_utils import bm25_scores, cosine_scores


EVIDENCE_PRIOR = {
    "Guideline": 0.08,
    "Meta-analysis": 0.07,
    "RCT": 0.06,
    "Consensus": 0.04,
    "Review": 0.03,
    "ClinicalTrial": 0.01,
    "preprint": -0.02,
    "Other": 0.0,
}


def rerank(question: str, entries: List[Entry], top_k: int = 8) -> List[Entry]:
    if not entries:
        return []
    searchable = [f"{entry.title} {entry.topic} {entry.text}" for entry in entries]
    lexical = bm25_scores(question, searchable)
    semantic = cosine_scores(question, searchable)
    for index, entry in enumerate(entries):
        source_prior = 0.04 if entry.source == "knowledge_page" else 0.0
        raw = (
            0.40 * lexical[index]
            + 0.30 * semantic[index]
            + 0.18 * entry.retrieval_score
            + source_prior
            + EVIDENCE_PRIOR.get(entry.evidence_level, 0.0)
        )
        entry.score = max(0.0, min(1.0, raw))
    ordered = sorted(entries, key=lambda item: item.score, reverse=True)[:top_k]
    for number, entry in enumerate(ordered, start=1):
        entry.citation_number = number
    return ordered
