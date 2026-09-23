#!/usr/bin/env python3
"""Run Arm A/B/C comparisons with shared preflight and privacy-safe records."""

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
from evidence_assistant.query_rewrite import redact_phi, rewrite
from evidence_assistant.refusal import assess_safety
from eval.baseline import call_baseline


def _safe_payload(value):
    """Exclude request text and diagnostics; redact known PHI patterns in output."""
    if isinstance(value, dict):
        return {key: _safe_payload(item) for key, item in value.items()
                if key not in {"question", "query_spec", "trace", "error", "original"}}
    if isinstance(value, list):
        return [_safe_payload(item) for item in value]
    return redact_phi(value) if isinstance(value, str) else value


def _arm_record(item: dict, arm: str, payload: dict, elapsed_ms, *,
                run_status: str = "success", error_code: str = "", status_reason: str = "") -> dict:
    answer = payload if arm == "A" else payload.get("answer", {})
    if run_status == "success" and type(answer.get("refused")) is not bool:
        raise ValueError("successful arm requires a boolean refusal status")
    return {
        "question_id": item["id"],
        "type": item.get("type", ""),
        "arm": arm,
        "elapsed_ms": elapsed_ms,
        "run_status": run_status,
        "answer_status": ("refused" if answer.get("refused") else "answered") if run_status == "success" else None,
        "error_code": error_code,
        "status_reason": status_reason,
        "payload": _safe_payload(payload),
    }


def _summarize(records: list) -> dict:
    by_arm = defaultdict(list)
    for record in records:
        by_arm[record["arm"]].append(record)
    summary = {}
    for arm, rows in sorted(by_arm.items()):
        successful = [row for row in rows if row["run_status"] == "success"]
        refusals = sum(row["answer_status"] == "refused" for row in successful)
        verified_outputs = 0
        for row in successful:
            payload = row["payload"]
            if arm != "A":
                check = payload.get("citation_check") or {}
                verified_outputs += bool(check.get("output_valid", False))
        summary[arm] = {
            "runs": len(rows),
            "successful": len(successful),
            "errors": sum(row["run_status"] == "error" for row in rows),
            "skipped": sum(row["run_status"] == "skipped" for row in rows),
            "answered": len(successful) - refusals,
            "refused": refusals,
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
    if require_baseline and not settings.llm_api_key:
        raise RuntimeError("Arm A requires LLM_API_KEY when --require-baseline is used")
    pipeline = None
    records = []
    for item in test_set:
        gate = assess_safety(rewrite(item["question"]))
        for arm in (["A", "B", "C"] if include_degraded else ["A", "B"]):
            if arm == "A" and not settings.llm_api_key:
                records.append(_arm_record(item, arm, {}, None, run_status="skipped", status_reason="baseline_not_configured"))
                continue
            started = time.perf_counter()
            try:
                if gate.refused:
                    # A blocked case retains only its ID and block code, never the input.
                    answer = {"refused": True, "refusal_code": gate.code}
                    payload = answer if arm == "A" else {"answer": answer, "retrieval_backend": "not_run", "rerank_backend": "not_run"}
                elif arm == "A":
                    payload = call_baseline(item["question"], settings)
                else:
                    if pipeline is None:
                        pipeline = EvidencePipeline(settings)
                    kwargs = {"retrieval_profile": "degraded"} if arm == "C" else {}
                    result = pipeline.run(item["question"], mode="hybrid", enable_live_apis=False, **kwargs)
                    payload = result.to_dict()
                records.append(_arm_record(item, arm, payload, int((time.perf_counter() - started) * 1000)))
            except Exception as error:
                records.append(_arm_record(item, arm, {}, int((time.perf_counter() - started) * 1000),
                                           run_status="error", error_code=type(error).__name__))

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
                "C": "legacy_degraded_smoke",
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
