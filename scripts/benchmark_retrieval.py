#!/usr/bin/env python3
"""Compare retrieval/rerank profiles on one frozen question set."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
for import_path in (ROOT, ROOT / "src"):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from config import settings
from evidence_assistant.pipeline import EvidencePipeline
from eval.metrics import mean, ndcg_at_k, recall_at_k, reciprocal_rank


def percentile(values, fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def evaluate_profile(profile: str, dataset: list, args) -> dict:
    try:
        retrieval_backend, rerank_backend = profile.split(":", 1)
    except ValueError as error:
        raise ValueError(f"Profile must be retrieval:rerank, got {profile!r}") from error
    cfg = replace(
        settings,
        retrieval_backend=retrieval_backend,
        rerank_backend=rerank_backend,
        embedding_model=args.embedding_model,
        embedding_model_revision=args.embedding_revision,
        rerank_model=args.rerank_model,
        rerank_model_revision=args.rerank_revision,
        vector_index_path=args.index_root,
        enable_live_apis=False,
    )
    pipeline = EvidencePipeline(cfg)
    rows = []
    topic_recalls = defaultdict(list)
    for item in dataset:
        result = pipeline.run(item["question"], mode=args.mode, enable_live_apis=False)
        relevant_ids = set(item.get("relevant_source_ids", []))
        relevant_topics = set(item.get("relevant_topics", []))
        seen = set()
        relevance = []
        for entry in result.entries:
            relevant = entry.doc_id in relevant_ids if relevant_ids else entry.topic in relevant_topics
            if relevant and entry.doc_id not in seen:
                relevance.append(2)
                seen.add(entry.doc_id)
            else:
                relevance.append(0)
        should_answer = bool(item.get("should_answer", True))
        recall = (
            recall_at_k(relevance, 8, total_relevant=len(relevant_ids) or None)
            if should_answer else None
        )
        if recall is not None:
            for topic in relevant_topics or {"unclassified"}:
                topic_recalls[topic].append(recall)
        supported = None
        if result.citation_check:
            supported = len(result.citation_check.supported_paragraphs) / max(
                result.answer.original_paragraph_count,
                len(result.answer.paragraphs),
                1,
            )
        identifier_question = bool(
            item.get("type") == "identifier"
            or re.search(r"\b(?:PMID|DOI|NCT\d{8})\b", item["question"], re.IGNORECASE)
        )
        rows.append({
            "id": item["id"],
            "recall_at_8": recall,
            "mrr": reciprocal_rank(relevance) if should_answer else None,
            "ndcg_at_8": (
                ndcg_at_k(relevance, 8, total_relevant=len(relevant_ids) or None)
                if should_answer else None
            ),
            "supported_claim_rate": supported,
            "elapsed_ms": result.elapsed_ms,
            "retrieval_backend": result.retrieval_backend,
            "rerank_backend": result.rerank_backend,
            "degraded": result.degraded,
            "degradation_reasons": result.degradation_reasons,
            "top_entry": result.entries[0].id if result.entries else "",
            "identifier_question": identifier_question,
            "identifier_top_1_correct": (
                bool(result.entries and result.entries[0].doc_id in relevant_ids)
                if identifier_question and relevant_ids
                else None
            ),
        })

    answerable = [row for row in rows if row["recall_at_8"] is not None]
    avg_latency = mean([float(row["elapsed_ms"]) for row in rows])
    p95_latency = percentile([row["elapsed_ms"] for row in rows], 0.95)
    topic_summary = {topic: mean(values) for topic, values in sorted(topic_recalls.items())}
    recall = mean([row["recall_at_8"] for row in answerable])
    ndcg = mean([row["ndcg_at_8"] for row in answerable])
    support_values = [row["supported_claim_rate"] for row in rows if row["supported_claim_rate"] is not None]
    support = mean(support_values)
    worst_topic = min(topic_summary.values(), default=0.0)
    latency_score = 1.0 / (1.0 + avg_latency / 2500.0)
    identifier_values = [
        row["identifier_top_1_correct"]
        for row in rows
        if row["identifier_top_1_correct"] is not None
    ]
    return {
        "profile": profile,
        "question_count": len(rows),
        "recall_at_8": recall,
        "mrr": mean([row["mrr"] for row in answerable]),
        "ndcg_at_8": ndcg,
        "supported_claim_rate": support,
        "worst_topic_recall_at_8": worst_topic,
        "topic_recall_at_8": topic_summary,
        "avg_elapsed_ms": avg_latency,
        "p95_elapsed_ms": p95_latency,
        "identifier_top_1_accuracy": (
            mean([float(value) for value in identifier_values]) if identifier_values else None
        ),
        "degraded_runs": sum(row["degraded"] for row in rows),
        "actual_retrieval_backends": dict(Counter(row["retrieval_backend"] for row in rows)),
        "actual_rerank_backends": dict(Counter(row["rerank_backend"] for row in rows)),
        "selection_score": (
            0.45 * recall
            + 0.25 * ndcg
            + 0.15 * support
            + 0.10 * worst_topic
            + 0.05 * latency_score
        ),
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "eval" / "test_set.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "eval_results" / "retrieval_benchmark.json")
    parser.add_argument("--mode", choices=["hybrid", "knowledge", "rag"], default="hybrid")
    parser.add_argument(
        "--profile",
        action="append",
        dest="profiles",
        help="Repeatable retrieval:rerank profile; defaults to legacy and configured candidates.",
    )
    parser.add_argument("--embedding-model", default=settings.embedding_model)
    parser.add_argument("--embedding-revision", default=settings.embedding_model_revision)
    parser.add_argument("--rerank-model", default=settings.rerank_model)
    parser.add_argument("--rerank-revision", default=settings.rerank_model_revision)
    parser.add_argument("--index-root", type=Path, default=settings.vector_index_path)
    args = parser.parse_args()
    profiles = args.profiles or [
        "legacy:deterministic",
        "dense:deterministic",
        "hybrid:deterministic",
        "hybrid:cross_encoder",
    ]
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    results = [evaluate_profile(profile, dataset, args) for profile in profiles]
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(args.dataset),
        "corpus_version": settings.corpus_version,
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "profiles": [
            {
                "profile": result["profile"],
                "recall_at_8": result["recall_at_8"],
                "ndcg_at_8": result["ndcg_at_8"],
                "avg_elapsed_ms": result["avg_elapsed_ms"],
                "p95_elapsed_ms": result["p95_elapsed_ms"],
                "degraded_runs": result["degraded_runs"],
                "selection_score": result["selection_score"],
            }
            for result in results
        ],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
