from __future__ import annotations

from typing import Dict, List

from .schemas import Answer, CheckedCitation, CitationCheck, Entry
from .text_utils import term_overlap


def _existence(entry: Entry) -> str:
    if entry.source != "knowledge_page":
        return "not_applicable"
    pmid_citations = [citation for citation in entry.citations if citation.type == "pmid"]
    if not pmid_citations:
        return "manual_review"
    if all(citation.pmid and citation.verified_at for citation in pmid_citations):
        return "verified_snapshot"
    return "unverified"


def _support(conclusion: str, entry: Entry, generator: str) -> str:
    if generator == "extractive" and conclusion.strip() == entry.text.strip():
        return "support"
    overlap = term_overlap(conclusion, entry.text)
    if overlap >= 0.14:
        return "support"
    if overlap >= 0.06:
        return "partial"
    return "unsupported"


def verify(answer: Answer, entries: List[Entry]) -> CitationCheck:
    by_number: Dict[int, Entry] = {entry.citation_number: entry for entry in entries}
    checked: List[CheckedCitation] = []
    stripped_paragraphs: List[int] = []
    failures = 0
    total = 0

    for paragraph_index, paragraph in enumerate(answer.paragraphs):
        paragraph_has_support = False
        if not paragraph.citation_ids:
            failures += 1
            total += 1
        for citation_id in paragraph.citation_ids:
            total += 1
            entry = by_number.get(citation_id)
            mapping_valid = entry is not None
            existence = _existence(entry) if entry else "not_checked"
            support = _support(paragraph.text, entry, answer.generator) if entry else "unsupported"
            valid = mapping_valid and existence != "unverified" and support == "support"
            if valid:
                paragraph_has_support = True
            else:
                failures += 1
            reasons = []
            if not mapping_valid:
                reasons.append("编号不在可引用列表")
            if existence == "unverified":
                reasons.append("知识页 PMID 尚未核对")
            if support != "support":
                reasons.append("引用未直接支持结论" if support == "unsupported" else "仅部分支持")
            checked.append(
                CheckedCitation(
                    paragraph_index=paragraph_index,
                    citation_id=citation_id,
                    entry_id=entry.id if entry else None,
                    mapping_valid=mapping_valid,
                    existence=existence,
                    support=support,
                    reason="；".join(reasons) or "通过编号、存在性与支持性校验",
                )
            )
        if not paragraph_has_support:
            stripped_paragraphs.append(paragraph_index)
    failure_ratio = failures / total if total else 1.0
    return CitationCheck(
        valid=failure_ratio == 0.0 and not stripped_paragraphs,
        checked=checked,
        failure_ratio=failure_ratio,
        stripped_paragraphs=stripped_paragraphs,
    )
