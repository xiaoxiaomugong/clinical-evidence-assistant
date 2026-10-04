import json
import logging
from uuid import uuid4

import pytest

from evidence_assistant.schemas import Answer, PipelineResult


@pytest.fixture(autouse=True)
def capture_private_runtime_logger(caplog):
    logger = logging.getLogger("evidence_assistant.runtime")
    logger.addHandler(caplog.handler)
    yield
    logger.removeHandler(caplog.handler)


def test_runtime_record_whitelist_excludes_content_credentials_and_opaque_values(caplog):
    from evidence_assistant.runtime_logging import RuntimeRecorder
    caplog.set_level(logging.INFO, logger="evidence_assistant.runtime")
    secret = "姓名张三 病历号 A123456 sk-synthetic https://private.invalid/question"
    recorder = RuntimeRecorder(str(uuid4()), "hybrid", corpus_version=secret)
    assert recorder.capture_content is False
    recorder("candidates", {"entries": [secret]})
    recorder("answer", {"answer": secret})
    recorder("error", {"error_type": secret, "trace": secret})
    recorder("timing", {"stage": secret, "status": secret, "elapsed_ms": 7, "trace": secret})
    recorder("timing", {"stage": "generate", "status": "success", "elapsed_ms": 2.5, "trace": secret})
    result = PipelineResult(secret, "hybrid", Answer(True, reason=secret, refusal_code=secret), [], None,
                            trace=[secret], retrieval_backend=secret, rerank_backend=secret,
                            degraded=True, degradation_reasons=[secret])
    recorder.finish("refused", queue_elapsed_ms=1, execution_elapsed_ms=3, result=result)
    assert len(caplog.records) == 1
    raw = caplog.records[0].message
    assert secret not in raw
    assert "张三" not in raw and "A123456" not in raw and "sk-synthetic" not in raw
    record = json.loads(raw)
    assert record["retrieval_backend"] == "unknown"
    assert record["rerank_backend"] == "unknown"
    assert record["corpus_version"] == "unknown"
    assert record["stage_timings"] == {"generate": {"status": "success", "elapsed_ms": 2.5}}
    assert set(record) <= {"schema_version", "request_id", "timestamp", "app_version", "corpus_version",
                          "mode", "status", "error_code", "queue_elapsed_ms", "execution_elapsed_ms",
                          "stage_timings", "retrieval_backend", "rerank_backend", "generator_backend",
                          "refusal_code", "degraded", "entry_count", "checked_citation_count",
                          "generation_entry_count", "dependency_states", "build_revision", "degradation_codes"}


def test_malformed_or_nonfinite_timing_values_do_not_enter_json(caplog):
    from evidence_assistant.runtime_logging import RuntimeRecorder
    caplog.set_level(logging.INFO, logger="evidence_assistant.runtime")
    recorder = RuntimeRecorder(str(uuid4()), "hybrid")
    for value in [float("nan"), float("inf"), -1, "sensitive", True]:
        recorder("timing", {"stage": "generate", "status": "success", "elapsed_ms": value})
    recorder("timing", {"stage": "verify", "status": "not_run", "elapsed_ms": None})
    recorder.finish("error", queue_elapsed_ms=float("nan"), execution_elapsed_ms=-2,
                    error_code="pipeline_error")
    record = json.loads(caplog.records[0].message)
    assert record["stage_timings"] == {"verify": {"status": "not_run", "elapsed_ms": None}}
    assert record["queue_elapsed_ms"] is None and record["execution_elapsed_ms"] is None
    assert "NaN" not in caplog.records[0].message


def test_default_runtime_logger_writes_stderr_and_keeps_stdout_clean(capsys):
    from evidence_assistant.runtime_logging import RuntimeRecorder
    logger = logging.getLogger("evidence_assistant.runtime")
    old_handlers, old_level, old_propagate = logger.handlers[:], logger.level, logger.propagate
    logger.handlers.clear()
    root = logging.getLogger()
    stdout_handler = logging.StreamHandler(__import__("sys").stdout)
    root.addHandler(stdout_handler)
    try:
        recorder = RuntimeRecorder(str(uuid4()), "rag")
        recorder.finish("busy", queue_elapsed_ms=0, execution_elapsed_ms=0, error_code="queue_timeout")
        captured = capsys.readouterr()
        assert captured.out == ""
        assert json.loads(captured.err)["status"] == "busy"
    finally:
        root.removeHandler(stdout_handler)
        logger.handlers[:] = old_handlers
        logger.setLevel(old_level)
        logger.propagate = old_propagate


def test_build_revision_accepts_only_hex_and_drops_git_error_output(caplog, monkeypatch):
    import evidence_assistant.runtime_logging as runtime
    from types import SimpleNamespace
    secret = "sk-synthetic private source path"
    caplog.set_level(logging.INFO, logger="evidence_assistant.runtime")
    monkeypatch.setenv("EVIDENCE_ASSISTANT_BUILD_SHA", secret)
    monkeypatch.setattr(runtime.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=secret, stderr=secret))
    runtime._build_revision.cache_clear()
    try:
        runtime.RuntimeRecorder(str(uuid4()), "hybrid").finish("error", queue_elapsed_ms=0,
                                                            execution_elapsed_ms=0, error_code="pipeline_error")
        record = json.loads(caplog.records[-1].message)
        assert record["build_revision"] == "unknown"
        assert secret not in caplog.records[-1].message
        monkeypatch.setenv("EVIDENCE_ASSISTANT_BUILD_SHA", "a" * 40)
        runtime._build_revision.cache_clear()
        runtime.RuntimeRecorder(str(uuid4()), "hybrid").finish("answered", queue_elapsed_ms=0, execution_elapsed_ms=0)
        assert json.loads(caplog.records[-1].message)["build_revision"] == "a" * 40
    finally:
        runtime._build_revision.cache_clear()


def test_runtime_generator_backend_reflects_actual_execution_on_early_gate(caplog):
    from evidence_assistant.runtime_logging import RuntimeRecorder
    from evidence_assistant.schemas import DependencyState
    caplog.set_level(logging.INFO, logger="evidence_assistant.runtime")
    result = PipelineResult("redacted", "hybrid", Answer(True, refusal_code="PHI_BLOCKED"), [], None,
                            dependency_states={"generator": DependencyState("not_attempted", "safety_gate")})
    RuntimeRecorder(str(uuid4()), "hybrid").finish("refused", queue_elapsed_ms=0,
                                                execution_elapsed_ms=1, result=result)
    record = json.loads(caplog.records[-1].message)
    assert record["generator_backend"] == "not_run"
    assert record["dependency_states"]["generator"]["reason_code"] == "safety_gate"


def test_logging_handler_failure_does_not_destroy_an_answer(monkeypatch):
    from evidence_assistant.runtime_logging import LOGGER
    from evidence_assistant.query_service import QueryService

    class BrokenHandler(logging.Handler):
        def emit(self, record):
            raise RuntimeError("sk-synthetic logging failure")

    class Pipeline:
        def run(self, question, mode="hybrid", enable_live_apis=None, *, recorder=None):
            return PipelineResult(question, mode, Answer(False), [], None)

    handler = BrokenHandler()
    LOGGER.addHandler(handler)
    try:
        result = QueryService(Pipeline()).run("clinical question")
        assert not result.answer.refused
        assert result.request_id
    finally:
        LOGGER.removeHandler(handler)


def test_backend_degradation_logs_only_known_reason_codes(caplog):
    from evidence_assistant.runtime_logging import RuntimeRecorder
    caplog.set_level(logging.INFO, logger="evidence_assistant.runtime")
    result = PipelineResult("private question", "hybrid", Answer(False), [], None, degraded=True,
                            degradation_reasons=["retrieval_backend_unavailable", "generator:timeout",
                                                 "sk-synthetic opaque error", "pubmed:private question"])
    RuntimeRecorder(str(uuid4()), "hybrid").finish("answered", queue_elapsed_ms=0,
                                                 execution_elapsed_ms=1, result=result)
    record = json.loads(caplog.records[-1].message)
    assert record["degradation_codes"] == ["retrieval_backend_unavailable", "generator:timeout"]
    assert "sk-synthetic" not in caplog.records[-1].message
    assert "private question" not in caplog.records[-1].message
