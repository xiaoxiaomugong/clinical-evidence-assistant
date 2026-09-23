import json
from dataclasses import replace

import pytest

from evidence_assistant.config import Settings
from eval import baseline, run_compare


@pytest.fixture
def offline_cfg(tmp_path, monkeypatch):
    cfg = replace(Settings(), llm_api_key="", enable_supabase=False, enable_live_apis=False,
                  supabase_url="", supabase_publishable_key="", supabase_secret_key="",
                  pubmed_api_key="", ncbi_email="", llm_base_url="https://example.invalid", llm_model="test",
                  retrieval_backend="legacy", rerank_backend="deterministic",
                  cache_dir=tmp_path / "cache", pdf_index_path=tmp_path / "absent.sqlite3")
    monkeypatch.setattr(run_compare, "settings", cfg)
    return cfg


@pytest.mark.parametrize("question,code", [
    ("姓名：张三，病历号 A123456，高血压该怎么办？", "PHI_BLOCKED"),
    ("我现在每天吃降压药，能不能停药？", "PERSONALIZED_TREATMENT"),
])
def test_baseline_blocks_unsafe_inputs_before_http(question, code, offline_cfg, monkeypatch):
    calls = []
    def external_call(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("unsafe baseline request reached HTTP")
    monkeypatch.setattr(baseline.requests, "post", external_call)
    result = baseline.call_baseline(question, replace(offline_cfg, llm_api_key="test-key"))
    assert result["refused"] is True
    assert result["refusal_code"] == code
    assert calls == []


def test_unconfigured_arm_is_skipped_and_has_no_quality_score(offline_cfg):
    report = run_compare.compare([{"id": "phi-1", "question": "姓名：张三，高血压的证据？"}])
    arm = next(record for record in report["records"] if record["arm"] == "A")
    assert arm["run_status"] == "skipped"
    assert arm["answer_status"] is None
    assert report["summary"]["A"]["skipped"] == 1
    assert report["summary"]["A"]["errors"] == 0
    assert report["summary"]["A"]["refusal_rate"] is None
    assert report["protocol"]["arms"]["C"] == "legacy_degraded_smoke"


def test_phi_is_blocked_in_every_arm_without_persisting_input_or_calling_pipeline(offline_cfg, monkeypatch):
    cfg = replace(offline_cfg, llm_api_key="synthetic-key")
    monkeypatch.setattr(run_compare, "settings", cfg)
    calls = []
    def prohibited(*args, **kwargs):
        calls.append(1)
        raise AssertionError("blocked question reached an adapter")
    monkeypatch.setattr(baseline.requests, "post", prohibited)
    monkeypatch.setattr(run_compare.EvidencePipeline, "run", prohibited)
    report = run_compare.compare([{"id": "phi-1", "question": "姓名：张三，病历号 A123456，高血压该怎么办？"}])
    assert calls == []
    assert all(row["run_status"] == "success" and row["answer_status"] == "refused" for row in report["records"])
    serialized = json.dumps(report, ensure_ascii=False)
    assert "张三" not in serialized
    assert "A123456" not in serialized
    assert "PHI_BLOCKED" in serialized
    assert all("question" not in row for row in report["records"])


def test_arm_errors_are_separate_and_do_not_abort_following_arms_or_leak_exception(offline_cfg, monkeypatch):
    monkeypatch.setattr(run_compare, "settings", replace(offline_cfg, llm_api_key="synthetic-key"))
    def fail(*args, **kwargs):
        raise RuntimeError("secret-key patient: 张三 raw-question")
    monkeypatch.setattr(run_compare, "call_baseline", fail)
    monkeypatch.setattr(run_compare.EvidencePipeline, "run", fail)
    report = run_compare.compare([{"id": "q-1", "question": "高血压的证据？"}])
    assert len(report["records"]) == 3
    assert all(row["run_status"] == "error" for row in report["records"])
    assert all(row["answer_status"] is None for row in report["records"])
    assert all(row["error_code"] == "RuntimeError" for row in report["records"])
    assert all(summary["errors"] == 1 and summary["refusal_rate"] is None for summary in report["summary"].values())
    assert "secret-key" not in json.dumps(report)
    assert "raw-question" not in json.dumps(report)


def test_summary_denominators_include_only_successful_answer_statuses():
    rows = [
        {"arm": "B", "run_status": "success", "answer_status": "answered", "elapsed_ms": 10, "payload": {"citation_check": {"output_valid": True}}},
        {"arm": "B", "run_status": "success", "answer_status": "refused", "elapsed_ms": 20, "payload": {}},
        {"arm": "B", "run_status": "error", "answer_status": None, "elapsed_ms": 1000, "payload": {}},
        {"arm": "B", "run_status": "skipped", "answer_status": None, "elapsed_ms": None, "payload": {}},
    ]
    result = run_compare._summarize(rows)["B"]
    assert result["runs"] == 4
    assert result["successful"] == 2
    assert result["errors"] == 1
    assert result["skipped"] == 1
    assert result["refusal_rate"] == 0.5
    assert result["verified_output_rate"] == 0.5
    assert result["avg_elapsed_ms"] == 15


def test_invalid_baseline_payload_does_not_count_as_answered(offline_cfg, monkeypatch):
    monkeypatch.setattr(run_compare, "settings", replace(offline_cfg, llm_api_key="synthetic-key"))
    monkeypatch.setattr(run_compare, "call_baseline", lambda *args: {})
    monkeypatch.setattr(run_compare.EvidencePipeline, "run", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("unavailable")))
    result = run_compare.compare([{"id": "q-1", "question": "高血压的证据？"}], include_degraded=False)
    assert result["records"][0]["run_status"] == "error"
    assert result["records"][0]["answer_status"] is None
    assert result["summary"]["A"]["successful"] == 0


def test_persisted_payload_omits_raw_question_and_diagnostics():
    record = run_compare._arm_record({"id": "q-1", "question": "clinical question"}, "B", {
        "question": "private request", "query_spec": {"original": "private request"},
        "answer": {"refused": False, "limitations": ["姓名：张三"]},
        "trace": ["raw adapter error"],
    }, 5)
    serialized = json.dumps(record, ensure_ascii=False)
    assert "private request" not in serialized
    assert "raw adapter error" not in serialized
    assert "张三" not in serialized
