from config import Settings
from evidence_assistant.generate import call_llm

from dataclasses import replace
import pytest
import requests

from evidence_assistant.generate import generate
from evidence_assistant.schemas import Entry
from evidence_assistant.pipeline import EvidencePipeline
from evidence_assistant.config import settings


@pytest.mark.parametrize("response_payload", [None, {}, {"choices": []},
    {"choices": [{"message": {"content": "not-json"}}]},
    {"choices": [{"message": {"content": '{"claims":"bad"}'}}]},
    {"choices": [{"message": {"content": '{}'}}]},
    {"choices": [{"message": {"content": '{"refused":"false","claims":[]}'}}]},
    {"choices": [{"message": {"content": '{"claims":[{"text":"Claim"}]}'}}]},
    {"choices": [{"message": {"content": '{"refused":false,"claims":[]}'}}]},
    {"choices": [{"message": {"content": '{"claims":[{"text":" ","citation_ids":[1]}]}'}}]},
])
def test_malformed_llm_response_falls_back_safely(monkeypatch, response_payload):
    class FakeResponse:
        def raise_for_status(self):
            return None
        def json(self):
            return response_payload
    monkeypatch.setattr("evidence_assistant.generate.requests.post", lambda *a, **k: FakeResponse())
    entries = [Entry(id="1", doc_id="pmid:1", source="pubmed", title="Study",
                     text="Supported statin evidence", evidence_level="RCT", citation_number=1)]
    answer = generate("What is the statin evidence?", entries, Settings(llm_api_key="synthetic-key"))
    assert answer.generator == "extractive"
    assert answer.generation_state.status == "fallback"
    assert answer.generation_state.reason_code == "invalid_response"
    assert answer.paragraphs[0].citation_ids == [1]


@pytest.mark.parametrize("status, reason", [(429, "rate_limited"), (503, "http_error")])
def test_llm_http_failure_reports_fixed_reason(monkeypatch, status, reason):
    class FakeResponse:
        status_code = status
        def raise_for_status(self):
            raise requests.HTTPError("secret-key INPUT URL", response=self)
    monkeypatch.setattr("evidence_assistant.generate.requests.post", lambda *a, **k: FakeResponse())
    answer = generate("question", [], Settings(llm_api_key="synthetic-key"))
    assert answer.generation_state.status == "fallback"
    assert answer.generation_state.reason_code == reason
    assert "secret-key" not in str(answer.generation_state)


def test_requests_bad_json_is_invalid_response(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None
        def json(self):
            raise requests.exceptions.JSONDecodeError("secret-key INPUT", "malformed", 0)
    monkeypatch.setattr("evidence_assistant.generate.requests.post", lambda *a, **k: FakeResponse())
    answer = generate("question", [], Settings(llm_api_key="synthetic-key"))
    assert answer.generation_state.status == "fallback"
    assert answer.generation_state.reason_code == "invalid_response"


def test_successful_llm_reports_success_without_model_configuration_in_state(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None
        def json(self):
            return {"choices": [{"message": {"content": '{"claims":[{"text":"Evidence","citation_ids":[1]}]}'}}]}
    monkeypatch.setattr("evidence_assistant.generate.requests.post", lambda *a, **k: FakeResponse())
    answer = generate("question", [], Settings(llm_api_key="synthetic-key", llm_model="model-secret"))
    assert answer.generation_state.status == "success"
    assert answer.generation_state.reason_code == "completed"
    assert answer.generation_state.actual_backend == "llm"
    assert answer.generation_state.result_count == 1
    assert "model-secret" not in str(answer.generation_state)


@pytest.mark.parametrize("citation_token", [
    "1e309", "-1e309", "NaN", "1e308", "1.5", "true", "null", '"broken"', "0", "-1",
])
def test_invalid_llm_citation_value_is_safe_fallback(monkeypatch, citation_token):
    class FakeResponse:
        def raise_for_status(self):
            return None
        def json(self):
            return {"choices": [{"message": {"content":
                '{"claims":[{"text":"Untrusted model claim","citation_ids":[' + citation_token + ']}]}'}}]}
    monkeypatch.setattr("evidence_assistant.generate.requests.post", lambda *a, **k: FakeResponse())
    entries = [Entry(id="1", doc_id="pmid:1", source="pubmed", title="Study",
                     text="Supported statin evidence", evidence_level="RCT", citation_number=1)]
    answer = generate("What is the statin evidence?", entries, Settings(llm_api_key="synthetic-key"))
    assert answer.generator == "extractive"
    assert answer.generation_state.status == "fallback"
    assert answer.generation_state.reason_code == "invalid_response"
    assert answer.paragraphs[0].text == "Supported statin evidence"
    assert answer.paragraphs[0].citation_ids == [1]


@pytest.mark.parametrize("citation_token", ["1", '"1"'])
def test_valid_integer_llm_citation_id_remains_supported(monkeypatch, citation_token):
    class FakeResponse:
        def raise_for_status(self):
            return None
        def json(self):
            return {"choices": [{"message": {"content":
                '{"claims":[{"text":"Evidence","citation_ids":[' + citation_token + ']}]}'}}]}
    monkeypatch.setattr("evidence_assistant.generate.requests.post", lambda *a, **k: FakeResponse())
    answer = generate("question", [], Settings(llm_api_key="synthetic-key"))
    assert answer.generation_state.status == "success"
    assert answer.paragraphs[0].citation_ids == [1]


def test_nonfinite_llm_citation_fallback_passes_actual_pipeline_safety_checks(monkeypatch, tmp_path):
    class FakeResponse:
        def raise_for_status(self):
            return None
        def json(self):
            return {"choices": [{"message": {"content":
                '{"claims":[{"text":"Untrusted model claim","citation_ids":[1e309]}]}'}}]}
    monkeypatch.setattr("evidence_assistant.generate.requests.post", lambda *a, **k: FakeResponse())
    events = []
    def timing_only(event, payload):
        events.append((event, payload))
    timing_only.capture_content = False
    cfg = replace(settings, cache_dir=tmp_path / "cache", enable_live_apis=False,
                  enable_supabase=False, llm_api_key="synthetic-key")
    result = EvidencePipeline(cfg).run("降压药应早上服用还是睡前服用？", recorder=timing_only)
    assert result.answer.generator == "extractive" and not result.answer.refused
    assert result.dependency_states["generator"].status == "fallback"
    assert result.dependency_states["generator"].reason_code == "invalid_response"
    assert result.degraded and "generator:invalid_response" in result.degradation_reasons
    assert result.evidence_gate and result.evidence_gate.independent_source_count >= 3
    assert result.citation_check and result.citation_check.valid and result.citation_check.output_valid
    assert result.citation_check.failure_ratio == 0
    assert "Untrusted model claim" not in str(result.to_dict())
    packet = set(result.generation_entry_ids)
    assert all(checked.entry_id in packet for checked in result.citation_check.checked)
    stages = {payload["stage"]: payload["status"] for event, payload in events if event == "timing"}
    assert all(stages[stage] == "success" for stage in ("evidence_gate", "generation_gate", "verify", "sanitize", "post_gate"))


def test_llm_timeout_is_configurable(monkeypatch):
    timeouts = []
    def fail(url, headers, json, timeout):
        timeouts.append(timeout)
        raise requests.Timeout("synthetic-key")
    monkeypatch.setattr("evidence_assistant.generate.requests.post", fail)
    cfg = replace(Settings(llm_api_key="synthetic-key"), llm_request_timeout=2.75)
    with pytest.raises(requests.Timeout):
        call_llm("question", cfg)
    assert timeouts == [2.75]


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), -1, 0])
def test_invalid_llm_timeout_uses_bounded_default(monkeypatch, timeout):
    captured = []
    def fail(*args, **kwargs):
        captured.append(kwargs["timeout"])
        raise requests.Timeout()
    monkeypatch.setattr("evidence_assistant.generate.requests.post", fail)
    cfg = replace(Settings(llm_api_key="synthetic-key"), llm_request_timeout=timeout)
    with pytest.raises(requests.Timeout):
        call_llm("question", cfg)
    assert captured == [45.0]


def test_call_llm_disables_thinking_for_deepseek(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"refused":false,"paragraphs":[{"text":"Evidence","citation_ids":[1]}],"limitations":[]}'
                            )
                        }
                    }
                ]
            }

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr("evidence_assistant.generate.requests.post", fake_post)
    cfg = Settings(
        llm_api_key="test-key",
        llm_base_url="https://api.deepseek.com",
        llm_model="deepseek-v4-flash",
    )

    answer = call_llm("json connection test", cfg)

    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["json"]["thinking"] == {"type": "disabled"}
    assert answer.generator == "llm:deepseek-v4-flash"
