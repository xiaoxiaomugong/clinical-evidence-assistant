import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import UUID

import pytest

from evidence_assistant.config import settings
from evidence_assistant.schemas import Answer, PipelineResult


class ControlledPipeline:
    def __init__(self):
        self.settings = replace(settings, corpus_version="v3")
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block = False
        self.fail = False
        self.recorder = object()

    def run(self, question, mode="hybrid", enable_live_apis=None, *, recorder=None):
        self.calls.append((question, mode, enable_live_apis))
        if recorder:
            recorder("timing", {"stage": "generate", "status": "success", "elapsed_ms": len(question)})
        self.entered.set()
        if self.block:
            assert self.release.wait(3), "test did not release controlled pipeline"
        if self.fail:
            raise RuntimeError("姓名张三 密钥 sk-synthetic https://private.invalid/trace")
        return PipelineResult(question, mode, Answer(False), [], None)


def service(pipeline, **options):
    from evidence_assistant.query_service import QueryService
    return QueryService(pipeline, **options)


@pytest.fixture(autouse=True)
def capture_private_runtime_logger(caplog):
    logger = logging.getLogger("evidence_assistant.runtime")
    logger.addHandler(caplog.handler)
    yield
    logger.removeHandler(caplog.handler)


@pytest.mark.parametrize("question,mode,live", [
    (None, "hybrid", None), ("   ", "hybrid", None),
    ("x" * 4001, "hybrid", None), ("question", "invalid", None),
    ("question", 1, None), ("question", "hybrid", "false"),
    ("question", "hybrid", 0),
])
def test_invalid_request_never_enters_pipeline(question, mode, live):
    pipeline = ControlledPipeline()
    with pytest.raises(ValueError) as caught:
        service(pipeline).run(question, mode, live)
    assert pipeline.calls == []
    assert UUID(caught.value.request_id).version == 4
    assert caught.value.error_code == "invalid_input"


def test_question_boundary_is_after_strip_and_mode_alias_is_normalized():
    pipeline = ControlledPipeline()
    result = service(pipeline).run("  " + "x" * 4000 + " \n", "知识页优先", False)
    assert result.question == "x" * 4000
    assert pipeline.calls == [("x" * 4000, "knowledge", False)]
    assert UUID(result.request_id).version == 4
    assert result.queue_elapsed_ms >= 0
    assert result.execution_elapsed_ms >= 0


def test_two_services_for_same_pipeline_cannot_overlap_and_ids_stay_local(caplog, monkeypatch):
    pipeline = ControlledPipeline()
    original_recorder = pipeline.recorder
    pipeline.block = True
    first = service(pipeline)
    second = service(pipeline)
    queued = threading.Event()
    original_wait = second._guard.condition.wait

    def announced_wait(timeout=None):
        assert 0 < timeout <= 5
        queued.set()
        return original_wait(timeout)

    monkeypatch.setattr(second._guard.condition, "wait", announced_wait)
    caplog.set_level("INFO", logger="evidence_assistant.runtime")
    with ThreadPoolExecutor(max_workers=2) as executor:
        a = executor.submit(first.run, "alpha")
        assert pipeline.entered.wait(2)
        b = executor.submit(second.run, "beta longer")
        assert queued.wait(2)
        assert pipeline.calls == [("alpha", "hybrid", None)]
        pipeline.release.set()
        results = [a.result(timeout=3), b.result(timeout=3)]
    assert [call[0] for call in pipeline.calls] == ["alpha", "beta longer"]
    assert results[0].request_id != results[1].request_id
    records = [json.loads(record.message) for record in caplog.records if record.name == "evidence_assistant.runtime"]
    by_id = {record["request_id"]: record for record in records}
    assert by_id[results[0].request_id]["stage_timings"]["generate"]["elapsed_ms"] == 5
    assert by_id[results[1].request_id]["stage_timings"]["generate"]["elapsed_ms"] == 11
    assert pipeline.recorder is original_recorder


def test_queue_timeout_is_explicit_and_does_not_enter_pipeline():
    from evidence_assistant.query_service import QueryBusyError
    pipeline = ControlledPipeline()
    pipeline.block = True
    with ThreadPoolExecutor(max_workers=1) as executor:
        running = executor.submit(service(pipeline).run, "first")
        assert pipeline.entered.wait(2)
        try:
            with pytest.raises(QueryBusyError) as caught:
                service(pipeline, max_wait_seconds=0).run("second")
            assert caught.value.error_code == "queue_timeout"
            assert "服务繁忙" in str(caught.value)
            assert pipeline.calls == [("first", "hybrid", None)]
        finally:
            pipeline.release.set()
        running.result(timeout=3)


def test_waiter_count_is_bounded_across_service_adapters(monkeypatch):
    from evidence_assistant.query_service import QueryBusyError
    pipeline = ControlledPipeline()
    pipeline.block = True
    limited = service(pipeline, max_waiters=1)
    queued = threading.Event()
    original_wait = limited._guard.condition.wait

    def announced_wait(timeout=None):
        queued.set()
        return original_wait(timeout)

    monkeypatch.setattr(limited._guard.condition, "wait", announced_wait)
    with ThreadPoolExecutor(max_workers=2) as executor:
        running = executor.submit(limited.run, "first")
        assert pipeline.entered.wait(2)
        waiting = executor.submit(service(pipeline, max_waiters=1).run, "second")
        assert queued.wait(2)
        try:
            with pytest.raises(QueryBusyError) as caught:
                service(pipeline, max_waiters=1).run("third")
            assert caught.value.error_code == "queue_full"
            assert len(pipeline.calls) == 1
        finally:
            pipeline.release.set()
        running.result(timeout=3)
        waiting.result(timeout=3)


def test_pipeline_exception_is_sanitized_and_unlocks_for_recovery():
    from evidence_assistant.query_service import QueryExecutionError
    pipeline = ControlledPipeline()
    pipeline.fail = True
    shared = service(pipeline)
    with pytest.raises(QueryExecutionError) as caught:
        shared.run("private synthetic input")
    assert caught.value.error_code == "pipeline_error"
    assert "sk-synthetic" not in str(caught.value)
    assert "张三" not in str(caught.value)
    failed_id = caught.value.request_id
    pipeline.fail = False
    recovered = shared.run("recover")
    assert not recovered.answer.refused
    assert recovered.request_id != failed_id


def test_different_pipelines_can_execute_concurrently():
    first, second = ControlledPipeline(), ControlledPipeline()
    first.block = True
    with ThreadPoolExecutor(max_workers=1) as executor:
        running = executor.submit(service(first).run, "one")
        assert first.entered.wait(2)
        try:
            result = service(second, max_wait_seconds=0).run("two")
            assert result.question == "two"
        finally:
            first.release.set()
        running.result(timeout=3)


@pytest.mark.parametrize("options", [
    {"max_wait_seconds": float("nan")}, {"max_wait_seconds": float("inf")},
    {"max_wait_seconds": -1}, {"max_waiters": -1}, {"max_waiters": True},
])
def test_invalid_queue_bounds_are_rejected(options):
    with pytest.raises(ValueError):
        service(ControlledPipeline(), **options)


def test_default_wait_budget_times_out_with_controlled_clock_and_then_recovers(monkeypatch):
    import evidence_assistant.query_service as module
    pipeline = ControlledPipeline()
    pipeline.block = True
    shared = service(pipeline)
    clock = {"now": 100.0}
    waits = []
    with ThreadPoolExecutor(max_workers=1) as executor:
        running = executor.submit(shared.run, "first")
        assert pipeline.entered.wait(2)
        monkeypatch.setattr(module.time, "monotonic", lambda: clock["now"])

        def expired_wait(timeout):
            waits.append(timeout)
            clock["now"] += timeout
            return False

        monkeypatch.setattr(shared._guard.condition, "wait", expired_wait)
        try:
            with pytest.raises(module.QueryBusyError) as caught:
                shared.run("timed out")
            assert caught.value.error_code == "queue_timeout"
            assert waits == [5.0]
            assert shared._guard.waiters == 0
            assert shared._guard.active is True
            assert len(pipeline.calls) == 1
        finally:
            pipeline.release.set()
        running.result(timeout=3)
    assert shared.run("recovery").question == "recovery"


@pytest.mark.parametrize("wake_time", [5.0, 6.0])
def test_queued_request_cannot_claim_freed_pipeline_at_or_after_deadline(monkeypatch, wake_time):
    import time
    from types import SimpleNamespace
    import evidence_assistant.query_service as module

    pipeline = ControlledPipeline()
    shared = service(pipeline)
    clock = {"now": 0.0}
    waits = []
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock["now"],
                                                       perf_counter=time.perf_counter))
    shared._guard.active = True

    def wake_after_release(timeout):
        waits.append(timeout)
        clock["now"] = wake_time
        shared._guard.active = False
        return True

    monkeypatch.setattr(shared._guard.condition, "wait", wake_after_release)
    with pytest.raises(module.QueryBusyError) as caught:
        shared.run("expired queued request")
    assert caught.value.error_code == "queue_timeout"
    assert waits == [5.0]
    assert pipeline.calls == []
    assert shared._guard.waiters == 0
    assert shared._guard.active is False
    # An idle pipeline needs no queue budget and remains available after expiry.
    result = service(pipeline, max_wait_seconds=0).run("immediate recovery")
    assert result.question == "immediate recovery"
    assert pipeline.calls == [("immediate recovery", "hybrid", None)]


def test_runtime_recorder_overrides_shared_content_recorder_without_mutation(tmp_path):
    from evidence_assistant.pipeline import EvidencePipeline
    cfg = replace(settings, cache_dir=tmp_path / "cache", enable_live_apis=False,
                  enable_supabase=False, llm_api_key="", retrieval_backend="legacy", rerank_backend="deterministic")
    captured = []
    recorder = lambda event, payload: captured.append((event, payload))
    pipeline = EvidencePipeline(cfg, recorder=recorder)
    captured.clear()
    result = service(pipeline).run("降压药应早上服用还是睡前服用？", enable_live_apis=False)
    assert not result.answer.refused
    assert captured == []
    assert pipeline.recorder is recorder
    assert result.to_dict()["request_id"] == result.request_id
    assert result.to_dict()["dependency_states"]["generator"]["actual_backend"] == "extractive"
