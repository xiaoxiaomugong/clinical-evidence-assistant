from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SourceCitation:
    type: str
    source: str
    pmid: Optional[str] = None
    chapter: Optional[str] = None
    url: Optional[str] = None
    verified_at: Optional[str] = None


@dataclass
class QuerySpec:
    original: str
    pico: Optional[Dict[str, str]]
    api_queries: List[str]
    local_terms: List[str]
    domains: List[str] = field(default_factory=list)
    out_of_scope: bool = False


@dataclass
class Document:
    id: str
    source: str
    title: str
    abstract: str
    journal: Optional[str] = None
    year: Optional[int] = None
    authors: List[str] = field(default_factory=list)
    study_type: Optional[str] = None
    status: Optional[str] = None
    evidence_level: str = "Other"
    url: str = ""
    retrieved_at: str = ""
    topic: str = ""


@dataclass
class Chunk:
    id: str
    doc_id: str
    source: str
    title: str
    text: str
    evidence_level: str
    url: str = ""
    journal: Optional[str] = None
    year: Optional[int] = None
    study_type: Optional[str] = None
    status: Optional[str] = None
    topic: str = ""
    citations: List[SourceCitation] = field(default_factory=list)
    retrieval_score: float = 0.0


@dataclass
class Entry:
    id: str
    doc_id: str
    source: str
    title: str
    text: str
    evidence_level: str
    url: str = ""
    journal: Optional[str] = None
    year: Optional[int] = None
    study_type: Optional[str] = None
    status: Optional[str] = None
    topic: str = ""
    citations: List[SourceCitation] = field(default_factory=list)
    retrieval_score: float = 0.0
    score: float = 0.0
    citation_number: int = 0


@dataclass
class AnswerParagraph:
    text: str
    citation_ids: List[int]


@dataclass
class Answer:
    refused: bool
    paragraphs: List[AnswerParagraph] = field(default_factory=list)
    reason: str = ""
    limitations: List[str] = field(default_factory=list)
    generator: str = "extractive"


@dataclass
class CheckedCitation:
    paragraph_index: int
    citation_id: int
    entry_id: Optional[str]
    mapping_valid: bool
    existence: str
    support: str
    reason: str


@dataclass
class CitationCheck:
    valid: bool
    checked: List[CheckedCitation] = field(default_factory=list)
    failure_ratio: float = 0.0
    stripped_paragraphs: List[int] = field(default_factory=list)


@dataclass
class PipelineResult:
    question: str
    mode: str
    answer: Answer
    entries: List[Entry]
    citation_check: Optional[CitationCheck]
    trace: List[str] = field(default_factory=list)
    query_spec: Optional[QuerySpec] = None
    used_live_api: bool = False
    elapsed_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
