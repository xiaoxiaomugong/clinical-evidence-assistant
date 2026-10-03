import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from evidence_assistant.tool import ClinicalEvidenceTool
from evidence_assistant.schemas import Answer, PipelineResult


def test_agent_tool_returns_complete_json_serializable_result():
    payload = ClinicalEvidenceTool().query(
        "降压药应早上服用还是睡前服用？",
        mode="hybrid",
        enable_live_apis=False,
    )

    assert payload["schema_version"] == "1.0"
    assert payload["status"] == "answered"
    assert payload["answer"]["refused"] is False
    assert payload["entries"]
    assert payload["citation_check"]["valid"] is True
    assert payload["disclaimer"]
    json.dumps(payload, ensure_ascii=False)


def test_agent_tool_preserves_pipeline_safety_refusal():
    payload = ClinicalEvidenceTool().query(
        "姓名：张三，病历号 A123456，高血压该怎么办？",
        enable_live_apis=True,
    )

    assert payload["status"] == "refused"
    assert payload["answer"]["refused"] is True
    assert payload["used_live_api"] is False
    assert payload["entries"] == []


@pytest.mark.parametrize(
    "question,mode,error",
    [
        ("   ", "hybrid", "不能为空"),
        ("高血压证据", "invalid", "不支持的 mode"),
    ],
)
def test_agent_tool_validates_inputs(question, mode, error):
    tool = ClinicalEvidenceTool()
    with pytest.raises(ValueError, match=error):
        tool.query(question, mode=mode)


def test_two_tool_adapters_share_the_pipeline_guard(monkeypatch):
    entered, release, queued = threading.Event(), threading.Event(), threading.Event()

    class Pipeline:
        def __init__(self):
            self.calls = []

        def run(self, question, mode="hybrid", enable_live_apis=None, *, recorder=None):
            self.calls.append(question)
            entered.set()
            assert release.wait(3)
            return PipelineResult(question, mode, Answer(False), [], None)

    pipeline = Pipeline()
    first, second = ClinicalEvidenceTool(pipeline=pipeline), ClinicalEvidenceTool(pipeline=pipeline)
    original_wait = second._service._guard.condition.wait

    def announced_wait(timeout=None):
        queued.set()
        return original_wait(timeout)

    monkeypatch.setattr(second._service._guard.condition, "wait", announced_wait)
    with ThreadPoolExecutor(max_workers=2) as executor:
        a = executor.submit(first.query, "first")
        assert entered.wait(2)
        b = executor.submit(second.query, "second")
        try:
            assert queued.wait(2)
            assert pipeline.calls == ["first"]
        finally:
            release.set()
        payloads = [a.result(timeout=3), b.result(timeout=3)]
    assert [payload["question"] for payload in payloads] == ["first", "second"]
    assert payloads[0]["request_id"] != payloads[1]["request_id"]


def test_tool_pipeline_failure_has_request_id_and_no_private_exception():
    class BrokenPipeline:
        def run(self, *args, **kwargs):
            raise RuntimeError("private synthetic patient sk-secret")

    with pytest.raises(RuntimeError) as caught:
        ClinicalEvidenceTool(pipeline=BrokenPipeline()).query("input")
    assert caught.value.request_id
    assert "sk-secret" not in str(caught.value)
