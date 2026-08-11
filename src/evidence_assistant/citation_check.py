from __future__ import annotations

import re
from collections import defaultdict
from typing import Dict, List

from .candidate_pool import canonical_source_id
from .schemas import Answer, AnswerParagraph, CheckedCitation, CitationCheck, Entry
from .text_utils import term_overlap


NUMBER_PATTERN = re.compile(r"(?<![\w.])\d+(?:,\d{3})*(?:\.\d+)?\s*%?")


def _existence(entry: Entry) -> str:
    if entry.source == "knowledge_page":
        pmid_citations = [citation for citation in entry.citations if citation.type == "pmid"]
        if pmid_citations:
            if all(citation.pmid and citation.url and citation.verified_at for citation in pmid_citations):
                return "verified_snapshot"
            return "unverified"
        if entry.citations and all(citation.url for citation in entry.citations):
            return "manual_review"
        return "unverified"

    source_id = canonical_source_id(entry)
    if source_id.startswith("pmid:"):
        return "source_record" if re.fullmatch(r"pmid:\d{5,9}", source_id) and entry.url else "unverified"
    if source_id.startswith("nct:"):
        return "source_record" if re.fullmatch(r"nct:NCT\d{8}", source_id) and entry.url else "unverified"
    if source_id.startswith("doi:"):
        return "source_record" if entry.url else "unverified"
    return "source_record" if entry.url and entry.id else "unverified"


def _normalized_numbers(text: str) -> set:
    values = set()
    for match in NUMBER_PATTERN.findall(text):
        normalized = match.replace(",", "").replace(" ", "")
        if normalized.endswith("%"):
            number = normalized[:-1].lstrip("0") or "0"
            values.add(f"{number}%")
        else:
            values.add(normalized.lstrip("0") or "0")
    return values


def _numeric_consistency(conclusion: str, evidence: str) -> bool:
    claimed = _normalized_numbers(conclusion)
    if not claimed:
        return True
    available = _normalized_numbers(evidence)
    return claimed.issubset(available)


def _evidence_text(entry: Entry) -> str:
    return " ".join(
        part
        for part in (entry.title, str(entry.year or ""), str(entry.status or ""), entry.text)
        if part
    )


def _support(conclusion: str, entry: Entry, generator: str) -> str:
    evidence = _evidence_text(entry)
    if not _numeric_consistency(conclusion, evidence):
        return "unsupported"
    if generator == "extractive" and conclusion.strip() == entry.text.strip():
        return "support"
    overlap = term_overlap(conclusion, evidence)
    if overlap >= 0.14:
        return "support"
    if overlap >= 0.06:
        return "partial"
    return "unsupported"


def _check_is_usable(item: CheckedCitation) -> bool:
    return (
        item.mapping_valid
        and item.existence not in {"unverified", "not_checked"}
        and item.support == "support"
        and item.numeric_consistent
    )


def verify(answer: Answer, entries: List[Entry]) -> CitationCheck:
    by_number: Dict[int, Entry] = {entry.citation_number: entry for entry in entries}
    checked: List[CheckedCitation] = []
    stripped_paragraphs: List[int] = []
    supported_paragraphs: List[int] = []
    failed_paragraphs = 0
    removed_citations = 0

    for paragraph_index, paragraph in enumerate(answer.paragraphs):
        paragraph_has_support = False
        if not paragraph.citation_ids:
            failed_paragraphs += 1
            stripped_paragraphs.append(paragraph_index)
            continue
        for citation_id in dict.fromkeys(paragraph.citation_ids):
            entry = by_number.get(citation_id)
            mapping_valid = entry is not None
            existence = _existence(entry) if entry else "not_checked"
            numeric_consistent = _numeric_consistency(paragraph.text, _evidence_text(entry)) if entry else False
            support = _support(paragraph.text, entry, answer.generator) if entry else "unsupported"
            reasons = []
            if not mapping_valid:
                reasons.append("编号不在可引用列表")
            if existence == "unverified":
                reasons.append("来源标识或 URL 尚未核对")
            if not numeric_consistent:
                reasons.append("陈述中的数字未在证据片段中出现")
            if support != "support":
                reasons.append("引用未直接支持陈述" if support == "unsupported" else "仅部分支持")
            item = CheckedCitation(
                paragraph_index=paragraph_index,
                citation_id=citation_id,
                entry_id=entry.id if entry else None,
                mapping_valid=mapping_valid,
                existence=existence,
                support=support,
                reason="；".join(dict.fromkeys(reasons)) or "通过编号、存在性、支持性与数字一致性校验",
                numeric_consistent=numeric_consistent,
            )
            checked.append(item)
            if _check_is_usable(item):
                paragraph_has_support = True
            else:
                removed_citations += 1
        if paragraph_has_support:
            supported_paragraphs.append(paragraph_index)
        else:
            stripped_paragraphs.append(paragraph_index)
            failed_paragraphs += 1

    paragraph_count = len(answer.paragraphs)
    failure_ratio = failed_paragraphs / paragraph_count if paragraph_count else 1.0
    completely_valid = failure_ratio == 0.0 and removed_citations == 0
    return CitationCheck(
        valid=completely_valid,
        checked=checked,
        failure_ratio=failure_ratio,
        stripped_paragraphs=stripped_paragraphs,
        supported_paragraphs=supported_paragraphs,
        removed_citation_count=removed_citations,
        output_valid=bool(supported_paragraphs),
    )


def sanitize_answer(answer: Answer, check: CitationCheck) -> Answer:
    """Remove unsupported claims and unusable citations before any UI can render them."""
    usable_by_paragraph = defaultdict(list)
    for item in check.checked:
        if _check_is_usable(item):
            usable_by_paragraph[item.paragraph_index].append(item.citation_id)

    paragraphs = []
    for index, paragraph in enumerate(answer.paragraphs):
        citation_ids = list(dict.fromkeys(usable_by_paragraph.get(index, [])))
        if not citation_ids:
            continue
        paragraphs.append(
            AnswerParagraph(
                text=paragraph.text,
                citation_ids=citation_ids,
                claim_type=paragraph.claim_type,
                certainty=paragraph.certainty,
            )
        )

    return Answer(
        refused=answer.refused,
        paragraphs=paragraphs,
        reason=answer.reason,
        refusal_code=answer.refusal_code,
        found=list(answer.found),
        missing=list(answer.missing),
        next_steps=list(answer.next_steps),
        limitations=list(answer.limitations),
        generator=answer.generator,
        original_paragraph_count=len(answer.paragraphs),
        removed_paragraph_count=len(answer.paragraphs) - len(paragraphs),
    )
