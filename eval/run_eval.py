from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from config import settings
from evidence_assistant.pipeline import EvidencePipeline
from evidence_assistant.text_utils import term_overlap
from eval.metrics import mean, ndcg_at_k, recall_at_k, reciprocal_rank


def write_svg(summary: dict, path: Path) -> None:
    metrics = [
        ("Recall@8", summary["recall_at_8"]),
        ("MRR", summary["mrr"]),
        ("nDCG@8", summary["ndcg_at_8"]),
        ("Citation accuracy", summary["citation_accuracy"]),
        ("Key-point coverage", summary["key_point_coverage"]),
        ("Refusal accuracy", summary["refusal_accuracy"]),
    ]
    rows = []
    for index, (label, value) in enumerate(metrics):
        y = 65 + index * 54
        width = round(520 * value, 1)
        rows.append(
            f'<text x="24" y="{y + 17}" class="label">{label}</text>'
            f'<rect x="205" y="{y}" width="520" height="24" rx="7" fill="#e5f0ed"/>'
            f'<rect x="205" y="{y}" width="{width}" height="24" rx="7" fill="#0b7b75"/>'
            f'<text x="742" y="{y + 17}" class="value">{value:.1%}</text>'
        )
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="840" height="430" viewBox="0 0 840 430">
<style>.title{{font:700 22px system-ui;fill:#102a2e}}.sub{{font:13px system-ui;fill:#61777a}}.label{{font:14px system-ui;fill:#243f43}}.value{{font:700 14px system-ui;fill:#0b5f5a}}</style>
<rect width="840" height="430" rx="18" fill="#f7faf8"/>
<text x="24" y="34" class="title">Bundled offline evaluation</text>
<text x="24" y="53" class="sub">{summary['question_count']} fixed questions · corpus {summary['corpus_version']} · mode {summary['mode']}</text>
{''.join(rows)}
<text x="24" y="411" class="sub">Engineering regression metrics; not a clinical validation study.</text>
</svg>'''
    path.write_text(svg, encoding="utf-8")


def evaluate(mode: str, output_dir: Path) -> dict:
    with (ROOT / "eval" / "test_set.json").open("r", encoding="utf-8") as handle:
        test_set = json.load(handle)
    pipeline = EvidencePipeline(settings)
    rows = []

    for item in test_set:
        result = pipeline.run(item["question"], mode=mode, enable_live_apis=False)
        topics = set(item["relevant_topics"])
        relevant_source_ids = set(item.get("relevant_source_ids", []))
        seen_relevant_sources = set()
        relevance = []
        for entry in result.entries:
            is_relevant = entry.doc_id in relevant_source_ids if relevant_source_ids else entry.topic in topics
            if is_relevant and entry.doc_id not in seen_relevant_sources:
                relevance.append(2)
                seen_relevant_sources.add(entry.doc_id)
            else:
                relevance.append(0)
        should_answer = bool(item["should_answer"])
        refusal_correct = result.answer.refused != should_answer
        checked = result.citation_check.checked if result.citation_check else []
        citation_accuracy = (
            sum(
                check.mapping_valid
                and check.support == "support"
                and check.existence not in {"unverified", "not_checked"}
                and check.numeric_consistent
                for check in checked
            )
            / len(checked)
            if checked else (None if result.answer.refused else 0.0)
        )
        answer_text = " ".join(paragraph.text for paragraph in result.answer.paragraphs)
        key_points = item.get("expected_key_points", [])
        coverage = (
            sum(term_overlap(point, answer_text) > 0 for point in key_points) / len(key_points)
            if key_points else 1.0
        )
        rows.append({
            "id": item["id"],
            "type": item["type"],
            "question": item["question"],
            "should_answer": should_answer,
            "refused": result.answer.refused,
            "refusal_correct": refusal_correct,
            "recall_at_8": recall_at_k(
                relevance,
                8,
                total_relevant=len(relevant_source_ids) if relevant_source_ids else None,
            ) if should_answer else None,
            "mrr": reciprocal_rank(relevance) if should_answer else None,
            "ndcg_at_8": ndcg_at_k(
                relevance,
                8,
                total_relevant=len(relevant_source_ids) if relevant_source_ids else None,
            ) if should_answer else None,
            "citation_accuracy": citation_accuracy,
            "supported_claim_rate": (
                len(result.citation_check.supported_paragraphs)
                / max(result.answer.original_paragraph_count, len(result.answer.paragraphs), 1)
                if result.citation_check else None
            ),
            "independent_sources": (
                result.evidence_gate.independent_source_count if result.evidence_gate else 0
            ),
            "evidence_roles": sorted({entry.evidence_role for entry in result.entries}),
            "key_point_coverage": coverage,
            "top_entry": result.entries[0].id if result.entries else "",
            "top_score": result.entries[0].score if result.entries else 0.0,
            "elapsed_ms": result.elapsed_ms,
            "retrieval_backend": result.retrieval_backend,
            "rerank_backend": result.rerank_backend,
            "degraded": result.degraded,
            "degradation_reasons": result.degradation_reasons,
            "answer": result.to_dict()["answer"],
        })

    answerable = [row for row in rows if row["should_answer"]]
    summary = {
        "corpus_version": settings.corpus_version,
        "mode": mode,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "question_count": len(rows),
        "recall_at_8": mean([row["recall_at_8"] for row in answerable]),
        "mrr": mean([row["mrr"] for row in answerable]),
        "ndcg_at_8": mean([row["ndcg_at_8"] for row in answerable]),
        "citation_accuracy": mean(
            [row["citation_accuracy"] for row in rows if row["citation_accuracy"] is not None]
        ),
        "supported_claim_rate": mean(
            [row["supported_claim_rate"] for row in rows if row["supported_claim_rate"] is not None]
        ),
        "key_point_coverage": mean([row["key_point_coverage"] for row in answerable]),
        "refusal_accuracy": mean([float(row["refusal_correct"]) for row in rows]),
        "avg_elapsed_ms": mean([float(row["elapsed_ms"]) for row in rows]),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / f"eval_{mode}.json").open("w", encoding="utf-8") as handle:
        json.dump({"summary": summary, "rows": rows}, handle, ensure_ascii=False, indent=2)
    fieldnames = [key for key in rows[0] if key != "answer"]
    with (output_dir / f"eval_{mode}.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows({key: row[key] for key in fieldnames} for row in rows)
    write_svg(summary, output_dir / f"eval_{mode}.svg")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the fixed offline evaluation set.")
    parser.add_argument("--mode", choices=["hybrid", "knowledge", "rag"], default="hybrid")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "eval_results")
    args = parser.parse_args()
    summary = evaluate(args.mode, args.output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
