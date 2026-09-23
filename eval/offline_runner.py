"""Private isolated worker for P0. Importing this module does not load Settings/.env."""
from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import json
import math
import os
from pathlib import Path
import resource
import socket
import sys
import time
from types import FunctionType

from eval.run_record import RunRecorder, summarize_results, write_json

HISTORICAL_ARMS = {"B0", "B1", "R1", "D1"}
SENSITIVE_SETTINGS = {"llm_api_key", "pubmed_api_key", "ncbi_email", "supabase_url",
                      "supabase_publishable_key", "supabase_secret_key"}
RETRIEVAL_RERANK_STAGES = {
    "knowledge_retrieval", "snapshot_retrieval", "pdf_retrieval", "cloud_retrieval", "static_selection",
    "preliminary_pool", "preliminary_rerank", "live_retrieval", "pool", "rerank", "top8_selection",
}


def settings_values(run: Path, profile: str, arm: str, cache: Path) -> dict:
    frozen = run / "frozen"
    return dict(
        root_dir=frozen, data_dir=frozen / "data", cache_dir=cache,
        knowledge_dir=frozen / "data/knowledge_pages",
        local_corpus_path=frozen / "data/raw/local_corpus.json",
        pdf_collection_dir=frozen / "500-collection",
        pdf_index_path=(run / "absent_c0/pdf.sqlite3" if profile == "C0"
                        else frozen / ("data/raw/pdf_collection_vnext.sqlite3" if arm in {"D1", "RD"}
                                       else "data/raw/pdf_collection.sqlite3")),
        corpus_version="v3", retrieval_backend="legacy", embedding_model="",
        embedding_model_revision="main", vector_index_path=cache / "absent_indexes",
        rerank_backend="deterministic", rerank_model="", rerank_model_revision="main",
        model_local_files_only=True, retrieve_k=40, lexical_retrieve_k=30, dense_retrieve_k=30,
        top_k=8, generation_top_k=5, embedding_batch_size=16, rerank_batch_size=16,
        minimum_independent_sources=3, rrf_k=60, pre_refusal_threshold=0.18,
        post_failure_threshold=0.5, request_timeout=12, rate_limit_seconds=0.35,
        api_max_attempts=3, live_cache_ttl_seconds=3600, enable_live_apis=False,
        filter_preprint=True, llm_api_key="", llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4.1-mini", pubmed_api_key="", ncbi_email="",
        enable_supabase=False, supabase_url="", supabase_publishable_key="",
        supabase_secret_key="", supabase_timeout=15,
        candidate_pool_policy="source_preserving" if arm in {"R1", "I1", "G1", "R2", "RD"} else "legacy",
        top8_selection_policy="document_diverse" if arm == "R2" else "legacy",
    )


def construct_settings(settings_class, values: dict, historical: bool = False):
    expected = {field.name for field in dataclasses.fields(settings_class)}
    values = dict(values)
    if historical:
        for field in ("candidate_pool_policy", "top8_selection_policy"):
            if field not in expected:
                values.pop(field, None)
    if set(values) != expected:
        raise ValueError("Settings fields not explicitly handled: missing=%s extra=%s" % (
            sorted(expected - set(values)), sorted(set(values) - expected)))
    if any(values.get(field) for field in SENSITIVE_SETTINGS):
        raise ValueError("Offline Settings must not contain credentials")
    if values["enable_live_apis"] or values["enable_supabase"] or not values["model_local_files_only"]:
        raise ValueError("Offline policy configuration violation")
    return settings_class(**values)


class AuditEvents(list):
    phase = "execution"


def install_network_guard():
    events = AuditEvents()
    denied = {"socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr",
              "socket.connect", "socket.sendto", "socket.sendmsg", "subprocess.Popen",
              "os.system", "os.posix_spawn"}

    def guard(event, args):
        if event in denied:
            events.append({"event": event, "phase": events.phase})
            raise PermissionError("P0 isolated worker denies network and child process execution")
    sys.addaudithook(guard)
    return events


def network_selftest(events) -> dict:
    events.phase = "selftest"
    checks = []
    try:
        def connect():
            with socket.socket() as handle:
                handle.connect(("127.0.0.1", 9))
        for operation in (lambda: socket.getaddrinfo("localhost", 9), connect):
            try:
                operation()
            except PermissionError:
                checks.append(True)
            else:
                checks.append(False)
    finally:
        events.phase = "execution"
    return {"passed": all(checks), "checks": checks,
            "scope": "Python audit hooks: socket DNS/connect/send and process launch; not OS packet capture"}


def load_dataset(path: Path) -> list:
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = payload.get("questions", []) if isinstance(payload, dict) else payload
    if not isinstance(items, list) or not items:
        raise ValueError("Dataset requires nonempty questions")
    if any(not isinstance(item.get("id"), str) or not isinstance(item.get("question"), str) for item in items):
        raise ValueError("Every dataset item requires string id and question")
    if len({item["id"] for item in items}) != len(items):
        raise ValueError("Question IDs must be unique")
    return items


def legacy_score(item: dict, result) -> dict:
    """Same frozen functions and binary relevance semantics as eval/run_eval.py."""
    from evidence_assistant.text_utils import term_overlap
    from eval.metrics import ndcg_at_k, recall_at_k, reciprocal_rank

    source_ids = set(item.get("relevant_source_ids", []))
    topics, seen, relevance = set(item.get("relevant_topics", [])), set(), []
    for entry in result.entries:
        relevant = entry.doc_id in source_ids if source_ids else entry.topic in topics
        if relevant and entry.doc_id not in seen:
            relevance.append(2)
            seen.add(entry.doc_id)
        else:
            relevance.append(0)
    should_answer = item.get("should_answer")
    checked = result.citation_check.checked if result.citation_check else []
    points = item.get("expected_key_points", [])
    text = " ".join(paragraph.text for paragraph in result.answer.paragraphs)
    return {
        "recall_at_8": recall_at_k(relevance, 8, total_relevant=len(source_ids) if source_ids else None) if should_answer else None,
        "mrr": reciprocal_rank(relevance) if should_answer else None,
        "ndcg_at_8": ndcg_at_k(relevance, 8, total_relevant=len(source_ids) if source_ids else None) if should_answer else None,
        "refusal_correct": result.answer.refused != should_answer if should_answer is not None else None,
        "citation_accuracy": sum(check.mapping_valid and check.support == "support" and
                                 check.existence not in {"unverified", "not_checked"} and check.numeric_consistent
                                 for check in checked) / len(checked) if checked else (None if result.answer.refused else 0.0),
        "supported_claim_rate": len(result.citation_check.supported_paragraphs) / max(
            result.answer.original_paragraph_count, len(result.answer.paragraphs), 1) if result.citation_check else None,
        "key_point_coverage": sum(term_overlap(point, text) > 0 for point in points) / len(points) if points else 1.0,
        "relevant_hits": sum(value > 0 for value in relevance[:8]) if should_answer else None,
        "relevant_total": len(source_ids) if should_answer else None,
    }


def public_result(result) -> dict:
    payload = result.to_dict()
    payload.pop("question", None)
    payload.pop("query_spec", None)
    return payload


def _pipeline(cfg, arm, recorder=None):
    from evidence_assistant.pipeline import EvidencePipeline
    pipeline = EvidencePipeline(cfg) if arm == "B0" else EvidencePipeline(cfg, recorder=recorder)
    if arm in HISTORICAL_ARMS and arm != "B0":
        if os.environ.get('CEA_ISOLATED_WORKER') != '1':
            raise RuntimeError('Historical safety policy requires an isolated offline worker')
        from evidence_assistant.candidate_pool import research_family_id
        from evidence_assistant.refusal import assess_evidence
        # Exact source-summary rule at baseline 1cc225b; all other gate checks
        # remain shared. Clone function globals instead of mutating the product
        # module, so a historical instance cannot change another pipeline.
        def historical_summary(entries):
            sources = {research_family_id(e) for e in entries if research_family_id(e)}
            return sorted({e.evidence_level for e in entries if e.evidence_level}), len(sources)
        historical_gate = FunctionType(assess_evidence.__code__,
            dict(assess_evidence.__globals__, _evidence_summary=historical_summary),
            argdefs=assess_evidence.__defaults__)
        pipeline._assess_top8_evidence = lambda spec, entries: historical_gate(
            spec, entries, cfg.pre_refusal_threshold, cfg.minimum_independent_sources)
    if arm in (HISTORICAL_ARMS - {'B0'}) | {'I1'}:
        if os.environ.get('CEA_ISOLATED_WORKER') != '1':
            raise RuntimeError('Historical generation policy requires an isolated offline worker')
        from evidence_assistant.schemas import EvidenceGateResult
        # Deliberately private to this isolated offline worker, never a product flag.
        pipeline._assess_generation_evidence = lambda spec, entries: EvidenceGateResult(refused=False)
    return pipeline


def run_regression(cfg, arm: str, profile: str, repeat: int, output: Path,
                   items: list, qrels=None, save_questions=False) -> list:
    recorder = RunRecorder(output, profile, arm, repeat, allow_raw_questions=save_questions)
    start = time.perf_counter()
    pipeline = _pipeline(cfg, arm, recorder)
    if arm == "B0":
        recorder("timing", {"stage": "initialization", "status": "success", "elapsed_ms": (time.perf_counter() - start) * 1000})
    rows = []
    for index, item in enumerate(items):
        recorder.start_question(item["id"], item["question"])
        started = time.perf_counter()
        try:
            result = pipeline.run(item["question"], mode="hybrid", enable_live_apis=False)
            payload = public_result(result)
            row = {"question_id": item["id"], "run_status": "success",
                   "answer_status": "refused" if result.answer.refused else "answered",
                   "should_answer": item.get("should_answer"),
                   "requested_backend": {"retrieval": "legacy", "rerank": "deterministic", "generation": "extractive"},
                   "actual_backend": {"retrieval": result.retrieval_backend, "rerank": result.rerank_backend,
                                      "generation": result.answer.generator if recorder.generated or (arm == "B0" and result.generation_entry_ids) else "not_run"},
                   "degraded": result.degraded, "degradation_reasons": result.degradation_reasons,
                   "actual_k": len(result.entries), "generation_k": len(result.generation_entry_ids),
                   "independent_source_count": result.evidence_gate.independent_source_count if result.evidence_gate else None,
                   "legacy": legacy_score(item, result), "pipeline": payload,
                   "graded": None, "elapsed_ms": (time.perf_counter() - started) * 1000}
            if qrels is not None:
                from eval.metrics_v2 import score_retrieval
                labels = qrels.get("qrels", qrels).get(item["id"], {})
                row["graded"] = score_retrieval([entry.doc_id for entry in result.entries], labels, k=8)
            if arm == "B0":
                recorder("candidates", {"stage": "top8", "phase": "final", "entries": payload["entries"]})
                recorder("answer", {"stage": "final", "answer": payload["answer"], "historical_raw_output": "unavailable"})
            recorder("timing", {"stage": "total", "status": "success", "elapsed_ms": row["elapsed_ms"]})
        except Exception as error:
            # Exception text/traceback may contain the original input. Persist only the class.
            row = {"question_id": item["id"], "run_status": "error", "answer_status": None,
                   "error_type": type(error).__name__, "legacy": None, "should_answer": item.get("should_answer"),
                   "requested_backend": {"retrieval": "legacy", "rerank": "deterministic", "generation": "extractive"},
                   "actual_backend": {"retrieval": "unknown", "rerank": "unknown", "generation": "unknown"}}
            recorder("timing", {"stage": "total", "status": "error", "elapsed_ms": (time.perf_counter() - started) * 1000})
        if index == 0:
            recorder("timing", {"stage": "first_request", "status": row["run_status"], "elapsed_ms": (time.perf_counter() - started) * 1000})
        recorder("timing", {"stage": "queue", "status": "success", "elapsed_ms": 0.0})
        recorder("result", row)
        recorder.finish_question()
        rows.append(row)
    write_json(output / "summary.json", summarize_results(rows))
    return rows


def quantiles(values: list) -> dict:
    ordered = sorted(values)
    return {"p%d_ms" % pct: ordered[math.ceil(pct / 100 * len(ordered)) - 1] if ordered else None for pct in (50, 95, 99)}


def run_performance(cfg, arm: str, items: list, trials: int) -> dict:
    if trials < 100:
        raise ValueError("Performance requires at least 100 trials per concurrency")
    answerable = [item for item in items if item.get("should_answer")]
    refusal_items = [item for item in items if item.get("should_answer") is False]
    if not answerable:
        return {"status": "not_evaluated", "reason": "No labeled answerable questions"}
    reports = []
    for concurrency in (1, 4):
        started = time.perf_counter()
        pipelines = [_pipeline(cfg, arm) for _ in range(concurrency)]
        initialization = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        pipelines[0].run(answerable[0]["question"], enable_live_apis=False)
        first = (time.perf_counter() - started) * 1000
        for i in range(10):
            pipelines[i % concurrency].run(answerable[i % len(answerable)]["question"], enable_live_apis=False)
        # One pipeline per thread; mutable backend status is never shared concurrently.
        import queue
        available = queue.Queue()
        for pipeline in pipelines:
            available.put(pipeline)

        def request(item, submitted):
            pipeline = available.get()
            began = time.perf_counter()
            timings = []
            if arm != "B0":
                def timing_recorder(event, payload):
                    if event == "timing":
                        timings.append(dict(payload))
                timing_recorder.capture_content = False
                pipeline.recorder = timing_recorder
            try:
                result = pipeline.run(item["question"], enable_live_apis=False)
                return {"question_id": item["id"], "queue_ms": (began - submitted) * 1000,
                        "wall_ms": (time.perf_counter() - began) * 1000, "run_status": "success",
                        "answer_status": "refused" if result.answer.refused else "answered",
                        "timings": timings,
                        "retrieval_rerank_ms": sum(row["elapsed_ms"] for row in timings
                                                   if row.get("stage") in RETRIEVAL_RERANK_STAGES
                                                   and row.get("elapsed_ms") is not None) if timings else None}
            except Exception as error:
                return {"question_id": item["id"], "queue_ms": (began - submitted) * 1000,
                        "wall_ms": (time.perf_counter() - began) * 1000, "run_status": "error",
                        "error_type": type(error).__name__}
            finally:
                available.put(pipeline)
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(request, answerable[i % len(answerable)], time.perf_counter()) for i in range(trials)]
            samples = [future.result() for future in futures]
            refusal = [executor.submit(request, item, time.perf_counter()).result() for item in refusal_items]
        answered = [sample for sample in samples if sample.get("answer_status") == "answered"]
        reports.append({"concurrency": concurrency, "initialization_ms": initialization, "first_request_ms": first,
                        "warmup_count": 10, "trial_count": trials, "actual_answered_count": len(answered),
                        "answer_trial_requirement_met": len(answered) >= 100,
                        "all_requests": quantiles([s["wall_ms"] for s in samples]),
                        "answered_requests": quantiles([s["wall_ms"] for s in answered]),
                        "retrieval_rerank": quantiles([s["retrieval_rerank_ms"] for s in samples
                                                       if s.get("retrieval_rerank_ms") is not None]),
                        "queue": quantiles([s["queue_ms"] for s in samples]),
                        "errors": sum(s["run_status"] == "error" for s in samples), "timeouts": None,
                        "timeout_policy": "Offline local calls have no imposed deadline; timeout rate not stress-tested",
                        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024),
                        "samples": samples, "refusal_fast_path": refusal})
    return {"status": "measured", "quantile_method": "nearest_rank", "profiles": reports,
            "retrieval_rerank_stages": sorted(RETRIEVAL_RERANK_STAGES),
            "memory_scope": "process peak RSS; later concurrency may include allocations from earlier runs",
            "cache_protocol": "separate pipeline instances; 10 warmups; frozen corpus; OS cache uncontrolled",
            "hardware_limitations": "Power mode, CPU frequency and system contention uncontrolled; GPU not evaluated"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--profile", choices=("C0", "C1"), required=True)
    parser.add_argument("--arm", choices=("B0", "B1", "R1", "I1", "G1", "R2", "D1", "RD"), required=True)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--performance", type=int, default=0)
    parser.add_argument("--save-questions", action="store_true")
    args = parser.parse_args(argv)
    if os.environ.get("CEA_ISOLATED_WORKER") != "1" or os.environ.get("EVIDENCE_ASSISTANT_ENV_FILE") != os.devnull:
        raise SystemExit("Worker must be launched through eval.run_p0 clean environment")
    output = args.run / args.profile / args.arm / ("performance" if args.performance else "repeat_%d" % args.repeat)
    output.mkdir(parents=True, exist_ok=False)
    events = install_network_guard()
    selftest = network_selftest(events)
    if not selftest["passed"]:
        raise SystemExit("Offline guard selftest failed")
    from evidence_assistant.config import Settings
    cfg = construct_settings(Settings, settings_values(args.run, args.profile, args.arm, output / "cache"), historical=args.arm == "B0")
    if args.profile == "C0" and cfg.pdf_index_path.exists():
        raise SystemExit("C0 PDF path must not exist")
    write_json(output / "settings.json", {key: value for key, value in dataclasses.asdict(cfg).items() if key not in SENSITIVE_SETTINGS})
    items = load_dataset(args.run / "frozen/eval/dataset.json")
    qrels_path = args.run / "frozen/eval/qrels.json"
    qrels = json.loads(qrels_path.read_text()) if qrels_path.exists() else None
    try:
        if args.performance:
            write_json(output / "performance.json", run_performance(cfg, args.arm, items, args.performance))
            failed = False
        else:
            rows = run_regression(cfg, args.arm, args.profile, args.repeat, output, items, qrels, args.save_questions)
            failed = any(row["run_status"] == "error" for row in rows)
    finally:
        write_json(output / "network_audit.json", {"selftest": selftest, "events": events,
                   "unexpected_network_attempts": sum(event["phase"] != "selftest" for event in events)})
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
