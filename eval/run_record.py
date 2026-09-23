"""Explicit local evaluation artifacts; never part of a product response."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

TIMING_STAGES = ("rewrite_safety", "knowledge_retrieval", "snapshot_retrieval", "pdf_retrieval",
                 "cloud_retrieval", "static_selection", "preliminary_pool", "preliminary_rerank",
                 "live_retrieval", "pool", "rerank", "top8_selection", "evidence_gate",
                 "generation_selection", "generation_gate", "generate", "verify", "sanitize", "post_gate",
                 "total", "queue")
NONDETERMINISTIC_FIELDS = {"elapsed_ms", "wall_ms", "created_at", "timestamp", "repeat"}


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def semantic_digest(value: Any) -> str:
    def stable(item):
        if isinstance(item, dict):
            return {key: stable(val) for key, val in item.items() if key not in NONDETERMINISTIC_FIELDS}
        if isinstance(item, list):
            return [stable(val) for val in item]
        return item
    encoded = json.dumps(stable(value), sort_keys=True, ensure_ascii=False, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


class RunRecorder:
    """Append deep snapshots, with dataset identifiers instead of user question text."""

    def __init__(self, output_dir: Path, profile: str, arm: str, repeat: int,
                 allow_raw_questions: bool = False):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.context = {"profile": profile, "arm": arm, "repeat": repeat, "question_id": "__initialization__"}
        self.allow_raw_questions = allow_raw_questions
        self._claims = []
        self._checked = {}
        self._surviving_claims = []
        self._timed = set()
        self._ranks = {}
        self.generated = False
        for name in ("candidates", "answers", "timings", "results"):
            (self.output_dir / (name + ".jsonl")).touch(exist_ok=True)

    def start_question(self, question_id: str, question: str = None) -> None:
        self.context["question_id"] = question_id
        self._claims, self._checked, self._timed = [], {}, set()
        self._ranks, self.generated = {}, False
        self._surviving_claims = []
        if question is not None and self.allow_raw_questions:
            from evidence_assistant.query_rewrite import rewrite
            spec = rewrite(question)
            if not spec.contains_phi:
                self._append("answers", {"stage": "controlled_dataset_input", "question": question})

    def _append(self, stream: str, payload: dict) -> None:
        record = copy.deepcopy(payload)
        record.update(self.context)
        with (self.output_dir / (stream + ".jsonl")).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def __call__(self, event: str, payload: dict) -> None:
        data = copy.deepcopy(payload)
        # Product events must not persist a raw question/query accidentally.
        for key in ("question", "query", "query_spec", "original", "safe_query"):
            data.pop(key, None)
        if event == "candidates":
            entries = data.pop("entries", [])
            components = data.pop("score_components", {})
            for rank, entry in enumerate(entries, 1):
                row = dict(data, **entry)
                row["entry_id"] = entry.get("id", entry.get("entry_id"))
                row.setdefault("rank", rank)
                if data.get("stage") == "reranked":
                    self._ranks[row["entry_id"]] = rank
                if data.get("stage") in {"reranked", "top8", "generation_top5"}:
                    row["rank_before_selection"] = self._ranks.get(row["entry_id"])
                    row["rank_after_selection"] = rank if data.get("stage") == "top8" else None
                row.setdefault("representation", "knowledge_claim" if entry.get("source") == "knowledge_page" else "document_chunk")
                row.setdefault("branch", entry.get("source", "unknown"))
                row.setdefault("text_sha256", hashlib.sha256(entry.get("text", "").encode()).hexdigest())
                row.setdefault("reason", "observed_at_stage")
                if components:
                    row["score_components"] = components.get(row["entry_id"])
                from evidence_assistant import candidate_pool
                citation_defaults = dict(pmid=None, doi=None, nct_id=None, chapter=None, url=None)
                identity = SimpleNamespace(**dict(dict(id="", doc_id="", source="", url=""), **entry))
                identity.citations = [SimpleNamespace(**dict(citation_defaults, **citation)) for citation in entry.get("citations", [])]
                row["document_identity"] = (candidate_pool.document_identity(identity) if hasattr(candidate_pool, "document_identity")
                                            else ("page:" + identity.doc_id if identity.source == "knowledge_page"
                                                  else "document:" + candidate_pool.canonical_source_id(identity)))
                row["family_id"] = candidate_pool.research_family_id(identity)
                row["identity_confidence"] = ("recognized" if hasattr(candidate_pool, "reliable_family_id") and
                                              candidate_pool.reliable_family_id(identity) else "unknown")
                self._append("candidates", row)
            if not entries:
                self._append("candidates", dict(data, entry_id=None, count=0, reason="empty_stage"))
        elif event == "candidate_decision":
            self._append("candidates", dict(data, event=event))
        elif event == "answer":
            stage = data.get("stage")
            paragraphs = data.get("answer", {}).get("paragraphs", [])
            claim_ids = data.get("claim_ids") or []
            if stage == "raw":
                self.generated = True
                self._claims = [dict(paragraph_index=i, claim_id=(self.context["question_id"] + ":" + claim_ids[i]
                    if i < len(claim_ids) else "%s:claim:%d:%s" % (
                    self.context["question_id"], i, hashlib.sha256(p.get("text", "").encode()).hexdigest()[:12])), **p)
                    for i, p in enumerate(paragraphs)]
                data["claims"] = copy.deepcopy(self._claims)
            elif stage == "checked":
                self._checked = data.get("check") or {}
                removed = []
                for index in self._checked.get("stripped_paragraphs", []):
                    if 0 <= index < len(self._claims):
                        reasons = [row.get("reason", "unspecified") for row in self._checked.get("checked", [])
                                   if row.get("paragraph_index") == index]
                        removed.append({"claim_id": self._claims[index]["claim_id"],
                                        "reason": "; ".join(reasons) or "unsupported_statement"})
                data["removed_claims"] = removed
            else:
                available = list(self._surviving_claims if stage == "final" and self._surviving_claims else self._claims)
                data["claims"] = []
                for index, paragraph in enumerate(paragraphs):
                    expected_id = self.context["question_id"] + ":" + claim_ids[index] if index < len(claim_ids) else None
                    match = next((p for p in available if (p["claim_id"] == expected_id if expected_id else
                                  p.get("text") == paragraph.get("text"))), None)
                    data["claims"].append(dict(paragraph, claim_id=match["claim_id"] if match else None,
                                               mapping_status="matched" if match else "unknown"))
                    if match:
                        available.remove(match)
                if stage == "sanitized":
                    self._surviving_claims = copy.deepcopy(data["claims"])
            self._append("answers", data)
        elif event == "error":
            self._append("answers", {"stage": "error", "error_type": data.get("error_type", "unknown")})
        elif event == "timing":
            self._timed.add(data.get("stage"))
            if data.get("status") == "not_run":
                data["elapsed_ms"] = None
            self._append("timings", data)
        elif event == "result":
            self._append("results", data)
        else:
            raise ValueError("Unknown evaluation event: " + event)

    def finish_question(self) -> None:
        for stage in TIMING_STAGES:
            if stage not in self._timed:
                self("timing", {"stage": stage, "status": "not_run", "elapsed_ms": None})


def summarize_results(rows: list) -> dict:
    counts = {status: sum(row.get("run_status") == status for row in rows)
              for status in ("success", "error", "skipped")}
    if sum(counts.values()) != len(rows):
        raise ValueError("Every result requires success/error/skipped run_status")
    quality = {}
    successful = [row for row in rows if row["run_status"] == "success"]
    for name in ("recall_at_8", "mrr", "ndcg_at_8", "citation_accuracy", "supported_claim_rate", "key_point_coverage", "refusal_accuracy"):
        key = "refusal_correct" if name == "refusal_accuracy" else name
        values = [row["legacy"][key] for row in successful
                  if row.get("legacy") and row["legacy"].get(key) is not None
                  and (name != "key_point_coverage" or row.get("should_answer"))]
        numerator = sum(values)
        quality[name] = {"value": numerator / len(values) if values else None,
                         "numerator": numerator, "denominator": len(values)}
    answerable = [row for row in rows if row.get("should_answer") and row["run_status"] != "skipped"]
    attempted = [row for row in rows if row["run_status"] != "skipped" and row.get("should_answer") is not None]
    coverage_total = sum((row.get("legacy") or {}).get("key_point_coverage") or 0 for row in answerable)
    behavior_total = sum(bool((row.get("legacy") or {}).get("refusal_correct")) for row in attempted)
    hits = sum((row.get("legacy") or {}).get("relevant_hits") or 0 for row in successful)
    relevant_total = sum((row.get("legacy") or {}).get("relevant_total") or 0 for row in successful)
    graded_counts = dict(judged=0, unjudged=0, no_qrels=0, failed=0, skipped=0)
    judged_rows = []
    for row in rows:
        scores = row.get("graded") or {}
        if row["run_status"] == "error":
            graded_counts["failed"] += 1
        elif row["run_status"] == "skipped":
            graded_counts["skipped"] += 1
        elif scores.get("ranking_comparable"):
            graded_counts["judged"] += 1
            judged_rows.append(row)
        elif scores.get("score_status") == "unjudged_candidates":
            graded_counts["unjudged"] += 1
        else:
            graded_counts["no_qrels"] += 1
    comparable = bool(rows) and graded_counts["judged"] == len(rows)
    graded = {"counts": graded_counts, "ranking_comparable": comparable,
              "reason": None if comparable else "Requested group is not fully comparable; do not rank arms by the judged subset",
              "judged_subset_diagnostic": {"scope": "Exploratory scored subset only; not a group ranking conclusion"}}
    for metric in ("recall_at_k", "recall_completion_at_k", "mrr_at_k", "ndcg_at_k"):
        values = [row["graded"][metric] for row in judged_rows if row["graded"].get(metric) is not None]
        diagnostic = {"value": sum(values) / len(values) if values else None, "denominator": len(values)}
        graded["judged_subset_diagnostic"][metric] = diagnostic
        graded[metric] = {"value": diagnostic["value"] if comparable else None,
                          "denominator": len(rows) if comparable else 0}
    return {"question_count": len(rows), "status_counts": counts,
            "answer_counts": {status: sum(row.get("answer_status") == status for row in successful)
                              for status in ("answered", "refused")},
            "quality": quality,
            "quality_scope": "legacy engineering proxies on successful runs; citation/support rules and lexical key-point overlap are not medical correctness",
            "legacy_relevant_source_hits": {"numerator": hits, "denominator": relevant_total,
                                             "value": hits / relevant_total if relevant_total else None},
            "intention_to_evaluate": {
                "policy": "errors contribute zero; skipped excluded",
                "legacy_rule_key_point_coverage": {"value": coverage_total / len(answerable) if answerable else None,
                                                   "numerator": coverage_total, "denominator": len(answerable)},
                "legacy_behavior_label_agreement": {"value": behavior_total / len(attempted) if attempted else None,
                                                    "numerator": behavior_total, "denominator": len(attempted)}},
            "graded_retrieval": graded,
            "question_outcomes": {row["question_id"]: {
                "expected_answer_status": ("answered" if row["should_answer"] else "refused") if row.get("should_answer") is not None else None,
                "answer_status": row.get("answer_status"), "run_status": row["run_status"]}
                for row in rows if row.get("question_id") is not None},
            "recall_at_40": {"value": None, "reason": "legacy has no unified ranked Top-40"},
            "formal_clinical_validation": {"value": None, "reason": "Independent blinded review and gold labels unavailable"},
            "intervals": {"value": None, "reason": "No reliable independent question-group labels; repeated runs are not independent samples"}}
