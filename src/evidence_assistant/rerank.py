from __future__ import annotations

from typing import List

from .candidate_pool import document_identity, reliable_family_id, research_family_id
from .schemas import Entry
from .text_utils import bm25_scores, cosine_scores, term_overlap


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


def evidence_role(level: str) -> str:
    if level in {"Guideline", "Meta-analysis", "Review", "Consensus"}:
        return "overview"
    if level == "RCT":
        return "causal"
    return "boundary"


def assign_citation_numbers(entries: List[Entry]) -> List[Entry]:
    for number, entry in enumerate(entries, start=1):
        entry.citation_number = number
    return entries


def select_top_k(entries: List[Entry], top_k: int = 8, policy: str = "legacy", on_decision=None) -> List[Entry]:
    """Select from the scored pool without increasing the retrieval budget."""
    if policy not in {"legacy", "document_diverse"}:
        raise ValueError(f"Unsupported Top-8 selection policy: {policy}")
    if top_k < 0:
        raise ValueError("top_k must be nonnegative")
    ordered = entries if policy == "legacy" else sorted(entries, key=lambda e: (-e.score, document_identity(e), e.id))
    selected, documents, families = [], set(), {}
    for rank, entry in enumerate(ordered, 1):
        doc, family = document_identity(entry), reliable_family_id(entry)
        reason = "retained"
        if len(selected) >= top_k:
            reason = "top_k_limit"
        elif policy == "document_diverse" and doc in documents:
            reason = "document_limit"
        elif policy == "document_diverse" and family and families.get(family, 0) >= 2:
            reason = "family_limit"
        else:
            selected.append(entry)
            documents.add(doc)
            if family:
                families[family] = families.get(family, 0) + 1
        if on_decision:
            on_decision({"entry_id": entry.id, "doc_id": entry.doc_id, "document_identity": doc,
                         "family_id": family, "rank_before_selection": rank, "reason": reason})
    return assign_citation_numbers(selected)


def score_details(question: str, entries: List[Entry]) -> dict:
    searchable = [f"{e.title} {e.topic} {e.text}" for e in entries]
    lexical = bm25_scores(question, searchable)
    cosine = cosine_scores(question, searchable)
    return {e.id: {"bm25": lexical[i], "tfidf_cosine": cosine[i], "retrieval_score": e.retrieval_score,
                   "source_prior": 0.04 if e.source == "knowledge_page" else 0.0,
                   "evidence_prior": EVIDENCE_PRIOR.get(e.evidence_level, 0.0)}
            for i, e in enumerate(entries)}


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
        entry.evidence_role = evidence_role(entry.evidence_level)
    ordered = sorted(entries, key=lambda item: item.score, reverse=True)[:top_k]
    return assign_citation_numbers(ordered)


def select_complementary(entries: List[Entry], max_items: int = 5) -> List[Entry]:
    """Build a small, diverse evidence packet without changing citation numbers."""
    if len(entries) <= max_items:
        return list(entries)

    selected: List[Entry] = []
    selected_ids = set()
    selected_sources = set()

    for role in ("overview", "causal", "boundary"):
        candidate = next(
            (
                entry
                for entry in entries
                if entry.evidence_role == role and research_family_id(entry) not in selected_sources
            ),
            None,
        )
        if candidate:
            selected.append(candidate)
            selected_ids.add(candidate.id)
            selected_sources.add(research_family_id(candidate))

    while len(selected) < max_items:
        remaining = [entry for entry in entries if entry.id not in selected_ids]
        if not remaining:
            break

        unseen_sources = [entry for entry in remaining if research_family_id(entry) not in selected_sources]
        pool = unseen_sources or remaining

        def mmr_score(entry: Entry) -> float:
            redundancy = max(
                (
                    max(term_overlap(entry.text, chosen.text), term_overlap(chosen.text, entry.text))
                    for chosen in selected
                ),
                default=0.0,
            )
            return 0.78 * entry.score - 0.22 * redundancy

        candidate = max(pool, key=mmr_score)
        selected.append(candidate)
        selected_ids.add(candidate.id)
        selected_sources.add(research_family_id(candidate))

    return sorted(selected, key=lambda entry: entry.citation_number)
