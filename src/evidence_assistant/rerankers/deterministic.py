from __future__ import annotations

from typing import List

from ..interfaces import BackendStatus
from ..rerank import rerank
from ..schemas import Entry


class DeterministicReranker:
    def __init__(self):
        self.status = BackendStatus(requested="deterministic", actual="deterministic")

    def reset_status(self) -> None:
        self.status = BackendStatus(requested="deterministic", actual="deterministic")

    def rerank(self, question: str, candidates: List[Entry], top_k: int) -> List[Entry]:
        self.reset_status()
        return rerank(question, candidates, top_k=top_k)
