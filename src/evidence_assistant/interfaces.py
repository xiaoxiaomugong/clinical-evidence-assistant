from __future__ import annotations

from dataclasses import dataclass
from typing import List, Protocol

from .schemas import Chunk, Entry, QuerySpec


@dataclass
class BackendStatus:
    """The requested and actual backend used for one pipeline run."""

    requested: str
    actual: str
    degraded: bool = False
    reason: str = ""


class Retriever(Protocol):
    status: BackendStatus

    def search(self, query_plan: QuerySpec, top_k: int) -> List[Chunk]: ...


class Reranker(Protocol):
    status: BackendStatus

    def rerank(self, question: str, candidates: List[Entry], top_k: int) -> List[Entry]: ...

    def reset_status(self) -> None: ...
