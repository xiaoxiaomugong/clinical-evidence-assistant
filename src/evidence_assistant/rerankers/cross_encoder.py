from __future__ import annotations

import math
from typing import Any, List, Optional

from ..interfaces import BackendStatus
from ..rerank import assign_citation_numbers, rerank
from ..schemas import Entry


class CrossEncoderReranker:
    """Optional cross-encoder with deterministic, fail-closed ranking fallback."""

    def __init__(
        self,
        model_name: str,
        model_revision: str = "main",
        batch_size: int = 16,
        local_files_only: bool = True,
        model: Optional[Any] = None,
    ):
        self.model_name = model_name
        self.model_revision = model_revision
        self.batch_size = batch_size
        self.local_files_only = local_files_only
        self._model = model
        self._load_error = ""
        self.status = BackendStatus(requested="cross_encoder", actual="cross_encoder")

    def reset_status(self) -> None:
        self.status = BackendStatus(requested="cross_encoder", actual="cross_encoder")

    def _load(self):
        if self._model is not None:
            return self._model
        if self._load_error:
            raise RuntimeError(self._load_error)
        if not self.model_name:
            self._load_error = "RERANK_MODEL is not configured"
            raise RuntimeError(self._load_error)
        try:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(
                self.model_name,
                revision=self.model_revision,
                local_files_only=self.local_files_only,
            )
        except Exception as error:  # optional model/runtime boundary
            self._load_error = (
                f"Cannot load rerank model {self.model_name}@{self.model_revision}: "
                f"{type(error).__name__}"
            )
            raise RuntimeError(self._load_error) from error
        return self._model

    @staticmethod
    def _probability(value: Any) -> float:
        if hasattr(value, "tolist"):
            value = value.tolist()
        if isinstance(value, (list, tuple)):
            value = value[-1]
        raw = float(value)
        if raw >= 0:
            return 1.0 / (1.0 + math.exp(-min(raw, 60.0)))
        exp_value = math.exp(max(raw, -60.0))
        return exp_value / (1.0 + exp_value)

    def _fallback(
        self,
        question: str,
        candidates: List[Entry],
        top_k: int,
        reason: str,
    ) -> List[Entry]:
        self.status = BackendStatus(
            requested="cross_encoder",
            actual="deterministic",
            degraded=True,
            reason=reason[:300],
        )
        return rerank(question, candidates, top_k=top_k)

    def rerank(self, question: str, candidates: List[Entry], top_k: int) -> List[Entry]:
        self.reset_status()
        if not candidates or top_k <= 0:
            return []
        legacy_order = rerank(question, candidates, top_k=len(candidates))
        pairs = [(question, f"{entry.title} {entry.topic} {entry.text}") for entry in legacy_order]
        try:
            model = self._load()
            raw_scores = model.predict(
                pairs,
                batch_size=self.batch_size,
                show_progress_bar=False,
            )
            scores = [self._probability(value) for value in raw_scores]
            if len(scores) != len(legacy_order):
                raise ValueError("Cross-encoder returned a different number of scores")
        except Exception as error:
            return self._fallback(
                question,
                legacy_order,
                top_k,
                str(error) or type(error).__name__,
            )

        for entry, cross_score in zip(legacy_order, scores):
            entry.score = max(0.0, min(1.0, 0.80 * cross_score + 0.20 * entry.score))
        ordered = sorted(legacy_order, key=lambda item: item.score, reverse=True)[:top_k]
        return assign_citation_numbers(ordered)
