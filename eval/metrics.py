from __future__ import annotations

import math
from typing import Iterable, List


def recall_at_k(relevance: Iterable[int], k: int) -> float:
    values = list(relevance)[:k]
    return 1.0 if any(value > 0 for value in values) else 0.0


def reciprocal_rank(relevance: Iterable[int]) -> float:
    for rank, value in enumerate(relevance, start=1):
        if value > 0:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(relevance: Iterable[int], k: int) -> float:
    values = list(relevance)[:k]
    dcg = sum((2 ** value - 1) / math.log2(index + 2) for index, value in enumerate(values))
    ideal = sorted(values, reverse=True)
    idcg = sum((2 ** value - 1) / math.log2(index + 2) for index, value in enumerate(ideal))
    return dcg / idcg if idcg else 0.0


def mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0
