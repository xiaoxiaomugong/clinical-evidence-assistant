#!/usr/bin/env python3
"""Run locked Arm A/B/C comparisons and persist every raw evaluation artifact."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from config import settings
from evidence_assistant.pipeline import EvidencePipeline
from eval.baseline import call_baseline


def _arm_record(item: dict, arm: str, payload: dict, elapsed_ms: int, error: str = "") -> dict:
    return {
        "question_id": item["id"],
        "question": item["question"],
        "type": item.get("type", ""),
        "arm": arm,
        "elapsed_ms": elapsed_ms,
        "error": error,
        "payload": payload,
    }


def _summarize(records: list) -> dict:
    by_arm = defaultdict(list)
    for record in records:
        by_arm[record["arm"]].append(record)
    summary = {}
    for arm, rows in sorted(by_arm.items()):
        successful = [row for row in rows if not row["error"]]
        refusals = 0
        verified_outputs = 0
        for row in successful:
            payload = row["payload"]
            if arm == "A":
                refusals += bool(payload.get("refused", False))
            else:
                answer = payload.get("answer", {})
                refusals += bool(answer.get("refused", False))
                check = payload.get("citation_check") or {}
                verified_outputs += bool(check.get("output_valid", False))
        summary[arm] = {
            "runs": len(rows),
            "successful": len(successful),
            "errors": len(rows) - len(successful),
            "refusal_rate": refusals / len(successful) if successful else None,
            "verified_output_rate": (
                verified_outputs / len(successful) if successful and arm != "A" else None
            ),
            "avg_elapsed_ms": (
                sum(row["elapsed_ms"] for row in successful) / len(successful) if successful else None
            ),
        }
    return summary


def compare(test_set: list, include_degraded: bool = True, require_baseline: bool = False) -> dict:
    pipeline = EvidencePipeline(settings)
    records = []
    for item in test_set:
        if settings.llm_api_key:
            started = time.perf_counter()
            try:
                payload = call_baseline(item["question"], settings)
                records.append(
                    _arm_record(item, "A", payload, int((time.perf_counter() - started) * 1000))
                )
            except Exception as error:
                records.append(
                    _arm_record(
                        item,
                        "A",
                        {},
                        int((time.perf_counter() - started) * 1000),
                        f"{type(error).__name__}: {error}",
                    )
                )
        elif require_baseline:
            raise RuntimeError("Arm A requires LLM_API_KEY when --require-baseline is used")
        else:
            records.append(_arm_record(item, "A", {}, 0, "LLM_API_KEY not configured; Arm A skipped"))

        result = pipeline.run(item["question"], mode="hybrid", enable_live_apis=False)
        records.append(_arm_record(item, "B", result.to_dict(), result.elapsed_ms))

        if include_degraded:
            degraded = pipeline.run(
                item["question"],
                mode="hybrid",
                enable_live_apis=False,
                retrieval_profile="degraded",
            )
            records.append(_arm_record(item, "C", degraded.to_dict(), degraded.elapsed_ms))

    return {
        "protocol": {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "model": settings.llm_model,
            "temperature": 0.2,
            "corpus_version": settings.corpus_version,
            "test_set_size": len(test_set),
            "live_apis": False,
            "arms": {
                "A": "pure LLM, no retrieval; same safety and JSON claim schema",
                "B": "normal offline RAG",
                "C": "deterministically degraded offline RAG",
            },
        },
        "summary": _summarize(records),
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-set", type=Path, default=ROOT / "eval" / "test_set.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "eval_results" / "compare")
    parser.add_argument("--no-degraded", action="store_true")
    parser.add_argument("--require-baseline", action="store_true")
    args = parser.parse_args()
    test_set = json.loads(args.test_set.read_text(encoding="utf-8"))
    report = compare(test_set, include_degraded=not args.no_degraded, require_baseline=args.require_baseline)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "protocol.json").write_text(
        json.dumps({"protocol": report["protocol"], "summary": report["summary"]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with (args.output / "records.jsonl").open("w", encoding="utf-8") as handle:
        for record in report["records"]:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps({"protocol": report["protocol"], "summary": report["summary"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
