from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from typing import Callable, Dict, Iterable, List, Optional

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


def document_identity(item) -> str:
    """A retrieved page is distinct from the papers it cites."""
    if item.source == "knowledge_page":
        return "page:" + item.doc_id
    # A publication's own identity takes precedence over a linked trial record.
    own = " ".join((item.doc_id, item.url))
    pmid = re.search(r"(?:pmid[:/]|pubmed\.ncbi\.nlm\.nih\.gov/)(\d{5,9})", own, re.I)
    if pmid:
        return "document:pmid:" + pmid.group(1)
    doi = re.search(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", own, re.I)
    if doi:
        return "document:doi:" + doi.group(0).rstrip(".,)").lower()
    return "document:" + canonical_source_id(item)


def reliable_family_id(item) -> str:
    if has_identity_conflict(item) or (item.source == 'knowledge_page' and
            any(len(values) > 1 for values in _identity_aliases(item).values())):
        return ""
    family = research_family_id(item)
    if re.fullmatch(r"pmid:\d{5,9}|(?:trial|nct):NCT\d{8}", family):
        return family
    if family.startswith("doi:10.") and "/" in family:
        return family
    if family.startswith("chapter:") and any(c.chapter and c.url for c in item.citations):
        return family
    return ""


def has_identity_conflict(item) -> bool:
    if item.source == "knowledge_page":
        return False  # Multiple cited publications are provenance, not page identity.
    return any(len(values) > 1 for values in _identity_aliases(item).values())


def _identity_aliases(item):
    own = "" if item.source == 'knowledge_page' else " ".join((item.doc_id, item.url))
    aliases = {
        "pmid": set(re.findall(r"(?:pmid[:/]|pubmed\.ncbi\.nlm\.nih\.gov/)(\d{5,9})", own, re.I)),
        "doi": {v.rstrip('.,)').lower() for v in re.findall(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", own, re.I)},
        "nct": {v.upper() for v in re.findall(r"\bNCT\d{8}\b", own, re.I)},
    }
    for citation in item.citations:
        for kind, value in (("pmid", citation.pmid), ("doi", citation.doi), ("nct", citation.nct_id)):
            if value:
                aliases[kind].add(str(value).upper() if kind == "nct" else str(value).lower().rstrip('.,)'))
    return aliases


def conflicted_document_ids(items):
    """Contradictory aliases across chunks cannot turn one paper into several."""
    documents = defaultdict(lambda: defaultdict(set))
    for item in items:
        if item.source != "knowledge_page":
            for kind, values in _identity_aliases(item).items():
                documents[document_identity(item)][kind].update(values)
    return {doc for doc, aliases in documents.items() if any(len(v) > 1 for v in aliases.values())}


def independent_source_count(items):
    # Components of publications and known family links. Page identity is
    # only an occupancy constraint: independently cited claims on one page
    # must not merge distinct studies. An ambiguous claim adds no sources.
    conflicts = conflicted_document_ids(items)
    parent = {}
    def find(key):
        parent.setdefault(key, key)
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key
    for item in items:
        doc, family = document_identity(item), reliable_family_id(item)
        if family and doc not in conflicts:
            if item.source != 'knowledge_page':
                parent[find(('document', doc))] = find(('family', family))
            find(('family', family))
            # Consistent PMID/DOI/NCT aliases connect the cited publication
            # to its trial; a page's own ID never creates a study-family edge.
            for kind, values in _identity_aliases(item).items():
                for value in values:
                    alias = ('trial:' if kind == 'nct' else kind + ':') + value
                    if re.fullmatch(r'pmid:\d{5,9}|trial:NCT\d{8}|doi:10\.\d{4,9}/\S+', alias):
                        parent[find(('family', alias))] = find(('family', family))
    return len({find(key) for key in parent})


def _text_hash(item) -> str:
    return hashlib.sha256(" ".join(item.text.lower().split()).encode("utf-8")).hexdigest()


def _preserve_sources(chunks, emit):
    conflicts = conflicted_document_ids(chunks)
    by_id = defaultdict(list)
    for chunk in chunks:
        by_id[chunk.id].append(_entry_from_chunk(chunk))
    winners = []
    for entry_id in sorted(by_id):
        versions = by_id[entry_id]
        if len({document_identity(v) for v in versions}) > 1 or any(document_identity(v) in conflicts for v in versions):
            for entry in versions:
                emit(entry, "identity_conflict")
            continue
        versions.sort(key=lambda v: (-v.retrieval_score, document_identity(v), _text_hash(v), v.source))
        winners.append(versions[0])
        for entry in versions[1:]:
            emit(entry, "duplicate_id", versions[0].id)
    winners.sort(key=lambda v: (-v.retrieval_score, document_identity(v), _text_hash(v), v.source, v.id))
    seen = {}
    result = []
    for entry in winners:
        key = (document_identity(entry), _text_hash(entry))
        if key in seen:
            emit(entry, "duplicate_text", seen[key])
        else:
            seen[key] = entry.id
            result.append(entry)
            emit(entry, "retained", entry.id)
    return result


def build(
    docs: Iterable[Document] = (),
    chunks: Iterable[Chunk] = (),
    pages: Iterable[Chunk] = (),
    *,
    policy: str = "legacy",
    on_decision: Optional[Callable[[dict], None]] = None,
) -> List[Entry]:
    if policy not in {"legacy", "source_preserving"}:
        raise ValueError(f"Unsupported candidate pool policy: {policy}")
    all_chunks = list(chunks) + list(pages)
    for document in docs:
        all_chunks.extend(document_to_chunks(document))

    def emit(entry, reason, survivor_id=None):
        if on_decision:
            on_decision({"entry_id": entry.id, "doc_id": entry.doc_id,
                         "document_identity": document_identity(entry), "source": entry.source,
                         "family_id": research_family_id(entry), "text_hash": _text_hash(entry),
                         "reason": reason, "survivor_id": survivor_id})

    if policy == "source_preserving":
        return _preserve_sources(all_chunks, emit)

    deduped: Dict[str, Entry] = {}
    text_seen = {}
    for chunk in all_chunks:
        text_key = " ".join(chunk.text.lower().split())[:600]
        if text_key in text_seen:
            emit(chunk, "legacy_text_prefix", text_seen[text_key])
            continue
        text_seen[text_key] = chunk.id
        entry = _entry_from_chunk(chunk)
        current = deduped.get(entry.id)
        if current is None or entry.retrieval_score > current.retrieval_score:
            if current is not None:
                emit(current, "duplicate_id", entry.id)
            deduped[entry.id] = entry
        else:
            emit(entry, "duplicate_id", current.id)

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
        for entry in entries[:2]:
            emit(entry, "retained", entry.id)
        for entry in entries[2:]:
            emit(entry, "legacy_family_cap")
    return result
