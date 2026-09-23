"""Versioned, document-level graded metrics; the legacy scorer stays frozen.

Grades are 0..3; Recall and MRR count grades >=2. An unjudged document in
the scoring budget makes scores unavailable, so missing labels never become
negative judgments. Repeated document positions consume budget and gain zero.
"""

from __future__ import annotations

import math
import random
from typing import Mapping, Sequence


SCORER_VERSION = "graded-doc-v2.0"


def score_retrieval(ranked_doc_ids: Sequence[str], qrels: Mapping[str, int], k: int = 8) -> dict:
    """Score the first K original positions, with full-qrels ideal gain.

    ``None`` is N/A, never a perfect score. ``slots`` retains all scoring
    decisions. MRR is capped at eight even when inspecting a larger K.
    ``recall_completion_at_k`` divides by min(K, relevant document count).
    """
    if type(k) is not int or k <= 0:
        raise ValueError("k must be a positive integer")
    if any(type(grade) is not int or not 0 <= grade <= 3 for grade in qrels.values()):
        raise ValueError("qrels grades must be integers in 0..3")
    total_relevant = sum(grade >= 2 for grade in qrels.values())
    reachable = min(k, total_relevant)
    seen = set()
    unjudged = []
    slots = []
    hits = 0
    reciprocal_rank = 0.0
    dcg = 0.0
    for rank, doc_id in enumerate(list(ranked_doc_ids)[:k], start=1):
        grade = qrels.get(doc_id)
        if doc_id in seen:
            status, gain = "duplicate", 0
        elif grade is None:
            status, gain = "unjudged", None
            unjudged.append(doc_id)
        else:
            status, gain = "judged", 2 ** grade - 1
            if grade >= 2:
                hits += 1
                if not reciprocal_rank and rank <= 8:
                    reciprocal_rank = 1.0 / rank
        seen.add(doc_id)
        if gain is not None:
            dcg += gain / math.log2(rank + 1)
        slots.append({"rank": rank, "doc_id": doc_id, "relevance": grade, "gain": gain, "status": status})
    idcg = sum((2 ** grade - 1) / math.log2(rank + 1)
               for rank, grade in enumerate(sorted(qrels.values(), reverse=True)[:k], start=1))
    status = "unjudged_candidates" if unjudged else "no_relevant_qrels" if not total_relevant else "scored"
    comparable = status == "scored"
    return {
        "scorer_version": SCORER_VERSION,
        "k": k,
        "mrr_k": min(k, 8),
        "returned_count": len(slots),
        "relevant_hits": hits,
        "total_relevant": total_relevant,
        "reachable_relevant": reachable,
        "duplicate_count": sum(slot["status"] == "duplicate" for slot in slots),
        "unjudged_doc_ids": unjudged,
        "ranking_comparable": comparable,
        "score_status": status,
        "recall_at_k": hits / total_relevant if comparable else None,
        "recall_completion_at_k": hits / reachable if comparable else None,
        "mrr_at_k": reciprocal_rank if comparable else None,
        "ndcg_at_k": dcg / idcg if comparable else None,
        "slots": slots,
    }


def _quantile(values: Sequence[float], fraction: float) -> float:
    position = (len(values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def paired_group_bootstrap(
    baseline: Mapping[str, Sequence[float]],
    candidate: Mapping[str, Sequence[float]],
    *,
    seed: int = 0,
    n_bootstrap: int = 2000,
    confidence: float = 0.95,
) -> dict:
    """Bootstrap predeclared groups, preserving a paired question-macro mean.

    Each sequence contains matched *question means* within its group. Callers
    must average repeated generations per question before supplying values.
    Resample group IDs, retain all questions in every selected group, then
    average their paired differences. Thus larger groups retain their question
    weight while repetitions do not increase the independent sample size. This
    method requires trustworthy group labels; it cannot create them for legacy
    data or certify an independent clinical evaluation.
    """
    if set(baseline) != set(candidate):
        raise ValueError("baseline and candidate must contain the same groups")
    if type(n_bootstrap) is not int or n_bootstrap < 1 or not 0 < confidence < 1:
        raise ValueError("n_bootstrap must be positive and confidence must be in (0,1)")
    group_differences = []
    n_observations = 0
    for group in sorted(baseline):
        before, after = list(baseline[group]), list(candidate[group])
        if not before or len(before) != len(after):
            raise ValueError("each group must contain nonempty paired observations")
        if not all(isinstance(value, (float, int)) and math.isfinite(value) for value in before + after):
            raise ValueError("observations must be finite numeric scores; exclude N/A explicitly")
        group_differences.append([right - left for left, right in zip(before, after)])
        n_observations += len(before)
    count = len(group_differences)
    rng = random.Random(seed)
    draws = []
    if count:
        for _ in range(n_bootstrap):
            sample = [difference for _ in range(count)
                      for difference in rng.choice(group_differences)]
            draws.append(sum(sample) / len(sample))
        draws.sort()
    tail = (1 - confidence) / 2
    return {
        "method": "paired_group_percentile_bootstrap",
        "estimand": "question_macro_mean_difference",
        "n_groups": count,
        "n_questions": n_observations,
        "n_observations": n_observations,
        "mean_difference": sum(sum(group) for group in group_differences) / n_observations if count else None,
        "ci_low": _quantile(draws, tail) if count else None,
        "ci_high": _quantile(draws, 1 - tail) if count else None,
        "confidence": confidence,
        "seed": seed,
        "n_bootstrap": n_bootstrap,
    }
