from dataclasses import replace
import json

import pytest
import requests

import evidence_assistant.pipeline as pipeline_module
from evidence_assistant.config import settings
from evidence_assistant.interfaces import BackendStatus
from evidence_assistant.pipeline import EvidencePipeline
from evidence_assistant.schemas import Document


QUESTION = "降压药应早上服用还是睡前服用？"
LIVE_KEYS = ("pubmed", "europepmc", "clinicaltrials")


def configured(tmp_path, **changes):
    cfg = replace(settings, cache_dir=tmp_path / "cache", enable_live_apis=False,
                  enable_supabase=False, llm_api_key="")
    return replace(cfg, **changes)


def install_sources(monkeypatch, outcomes):
    for key, name in zip(LIVE_KEYS, ("pubmed_search", "europepmc_search", "clinicaltrials_search")):
        def search(spec, top_k, cfg, outcome=outcomes[key]):
            assert top_k == 4
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        monkeypatch.setattr(pipeline_module, name, search)


def test_offline_generator_is_success_and_external_sources_disabled(tmp_path):
    result = EvidencePipeline(configured(tmp_path)).run(QUESTION)
    assert not result.degraded and not result.used_live_api
    assert result.dependency_states["generator"].status == "success"
    assert result.dependency_states["generator"].reason_code == "offline_extractive"
    assert result.dependency_states["generator"].actual_backend == "extractive"
    assert all(result.dependency_states[key].status == "disabled" for key in (*LIVE_KEYS, "supabase"))


@pytest.mark.parametrize("outcomes, expected, degraded", [
    ({"pubmed": [], "europepmc": [], "clinicaltrials": []},
     {"pubmed": "empty", "europepmc": "empty", "clinicaltrials": "empty"}, False),
    ({"pubmed": requests.Timeout("INPUT secret-key https://bad.test/?q=INPUT"),
      "europepmc": [], "clinicaltrials": []},
     {"pubmed": "error", "europepmc": "empty", "clinicaltrials": "empty"}, True),
    ({key: requests.ConnectionError("INPUT secret-key") for key in LIVE_KEYS},
     {key: "error" for key in LIVE_KEYS}, True),
])
def test_live_errors_and_empty_results_are_distinct(monkeypatch, tmp_path, outcomes, expected, degraded):
    install_sources(monkeypatch, outcomes)
    result = EvidencePipeline(configured(tmp_path, enable_live_apis=True)).run("最新" + QUESTION)
    assert result.used_live_api and result.degraded is degraded
    assert {key: result.dependency_states[key].status for key in LIVE_KEYS} == expected
    assert all(result.dependency_states[key].elapsed_ms >= 0 for key in LIVE_KEYS)
    assert "INPUT" not in json.dumps(result.to_dict()) and "secret-key" not in json.dumps(result.to_dict())
    if degraded:
        assert result.degradation_reasons
    else:
        assert result.degradation_reasons == []


def test_successful_live_source_records_count(monkeypatch, tmp_path):
    doc = Document(id="pmid:999999", source="pubmed", title="Unrelated study",
                   abstract="Unrelated study", evidence_level="RCT")
    install_sources(monkeypatch, {"pubmed": [doc], "europepmc": [], "clinicaltrials": []})
    result = EvidencePipeline(configured(tmp_path, enable_live_apis=True)).run("最新" + QUESTION)
    assert result.dependency_states["pubmed"].status == "success"
    assert result.dependency_states["pubmed"].result_count == 1
    assert not result.degraded


def test_live_local_priority_skip_is_not_attempted(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        pytest.fail("local evidence should skip live sources")
    for name in ("pubmed_search", "europepmc_search", "clinicaltrials_search"):
        monkeypatch.setattr(pipeline_module, name, forbidden)
    result = EvidencePipeline(configured(tmp_path, enable_live_apis=True)).run(QUESTION)
    assert not result.used_live_api
    assert all(result.dependency_states[key].status == "not_attempted" for key in LIVE_KEYS)
    assert all(result.dependency_states[key].reason_code == "local_evidence_sufficient" for key in LIVE_KEYS)


def test_phi_marks_dependencies_not_attempted_without_adapter_calls(monkeypatch, tmp_path):
    cfg = configured(tmp_path, enable_live_apis=True, enable_supabase=True,
                     supabase_url="", supabase_publishable_key="", llm_api_key="secret-key")
    pipe = EvidencePipeline(cfg)
    def forbidden(*args, **kwargs):
        pytest.fail("PHI reached an adapter")
    for name in ("pubmed_search", "europepmc_search", "clinicaltrials_search", "generate"):
        monkeypatch.setattr(pipeline_module, name, forbidden)
    monkeypatch.setattr(pipe.knowledge, "search", forbidden)
    result = pipe.run("姓名：张三，病历号 A123456，高血压该怎么办？")
    assert result.answer.refusal_code == "PHI_BLOCKED"
    assert all(state.status == "not_attempted" for state in result.dependency_states.values())
    assert all(state.reason_code == "safety_gate" for state in result.dependency_states.values())
    assert not result.degraded


@pytest.mark.parametrize("packet_gate", [False, True])
def test_evidence_gate_marks_generator_not_attempted(monkeypatch, tmp_path, packet_gate):
    pipe = EvidencePipeline(configured(tmp_path, llm_api_key="secret-key"))
    if packet_gate:
        monkeypatch.setattr(pipeline_module, "select_complementary", lambda rows, max_items: rows[:1])
    def forbidden(*args, **kwargs):
        pytest.fail("evidence gate should skip generator")
    monkeypatch.setattr(pipeline_module, "generate", forbidden)
    result = pipe.run(QUESTION if packet_gate else "虚构新药 XYZ 对高血压有什么疗效？")
    assert result.answer.refused
    assert result.dependency_states["generator"].status == "not_attempted"
    assert result.dependency_states["generator"].elapsed_ms == 0


@pytest.mark.parametrize("outcome, code", [
    (requests.Timeout("INPUT secret-key"), "timeout"),
    (ValueError("INPUT secret-key"), "invalid_response"),
    (KeyError("INPUT secret-key"), "invalid_response"),
])
def test_llm_fallback_is_degraded_and_still_checked(monkeypatch, tmp_path, outcome, code):
    def fail(*args, **kwargs):
        raise outcome
    monkeypatch.setattr("evidence_assistant.generate.call_llm", fail)
    result = EvidencePipeline(configured(tmp_path, llm_api_key="secret-key")).run(QUESTION)
    state = result.dependency_states["generator"]
    assert state.status == "fallback" and state.reason_code == code
    assert state.actual_backend == "extractive"
    assert result.degraded and f"generator:{code}" in result.degradation_reasons
    assert result.citation_check and result.citation_check.valid
    assert not result.answer.refused
    assert "INPUT" not in json.dumps(result.to_dict()) and "secret-key" not in json.dumps(result.to_dict())


def test_cloud_error_is_degraded_without_exception_leak(monkeypatch, tmp_path):
    pipe = EvidencePipeline(configured(tmp_path, enable_supabase=True))
    class BrokenCloud:
        def search(self, *args, **kwargs):
            raise pipeline_module.SupabaseStoreError("INPUT secret-key https://bad.test/?q=INPUT")
    pipe.supabase_corpus = BrokenCloud()
    result = pipe.run(QUESTION)
    assert result.dependency_states["supabase"].status == "error"
    assert result.degraded and "supabase:dependency_error" in result.degradation_reasons
    assert "INPUT" not in str(result.to_dict()) and "secret-key" not in str(result.to_dict())


def test_cloud_configuration_error_is_not_normal_disabled(tmp_path):
    result = EvidencePipeline(configured(tmp_path, enable_supabase=True)).run(QUESTION)
    assert result.dependency_states["supabase"].status == "error"
    assert result.dependency_states["supabase"].reason_code == "configuration_error"
    assert result.degraded


def test_backend_public_status_and_trace_never_echo_untrusted_configuration(monkeypatch, tmp_path):
    secret = "secret-key https://bad.test/?q=INPUT"
    pipe = EvidencePipeline(configured(tmp_path, retrieval_backend=secret, rerank_backend=secret))
    result = pipe.run(QUESTION)
    assert result.degraded
    assert result.degradation_reasons == ["retrieval_backend_invalid", "rerank_backend_invalid"]
    assert secret not in str(result.to_dict())


def test_backend_fallback_reason_is_a_safe_code(monkeypatch, tmp_path):
    pipe = EvidencePipeline(configured(tmp_path, retrieval_backend="dense"))
    monkeypatch.setattr(pipe.dense_retriever, "search", lambda *args, **kwargs: [])
    pipe.dense_retriever.status = BackendStatus("dense", "legacy", True, "secret-key URL INPUT")
    result = pipe.run(QUESTION)
    assert result.degradation_reasons == ["retrieval_backend_unavailable"]
    assert "secret-key" not in str(result.to_dict())


def test_request_recorder_override_does_not_mutate_shared_recorder(tmp_path):
    default_events, request_events = [], []
    default = lambda event, payload: default_events.append((event, payload))
    request = lambda event, payload: request_events.append((event, payload))
    pipe = EvidencePipeline(configured(tmp_path), recorder=default)
    default_events.clear()
    pipe.run(QUESTION, recorder=request)
    assert not default_events and request_events
    assert pipe.recorder is default
    pipe.run(QUESTION, recorder=None)
    assert not default_events
    pipe.run(QUESTION)
    assert default_events


def test_each_dependency_duration_uses_its_own_adapter_call(monkeypatch, tmp_path):
    now = [100.0]
    monkeypatch.setattr(pipeline_module.time, "perf_counter", lambda: now[0])
    for index, name in enumerate(("pubmed_search", "europepmc_search", "clinicaltrials_search"), 1):
        def empty(spec, top_k, cfg, seconds=index):
            now[0] += seconds
            return []
        monkeypatch.setattr(pipeline_module, name, empty)
    def failed_llm(*args, **kwargs):
        now[0] += 4
        raise requests.Timeout("private message")
    monkeypatch.setattr("evidence_assistant.generate.call_llm", failed_llm)
    result = EvidencePipeline(configured(tmp_path, enable_live_apis=True, llm_api_key="synthetic-key")).run("最新" + QUESTION)
    assert [result.dependency_states[key].elapsed_ms for key in LIVE_KEYS] == [1000, 2000, 3000]
    assert result.dependency_states["generator"].elapsed_ms == 4000


def test_dependency_states_from_prior_request_are_not_mutated(monkeypatch, tmp_path):
    cfg = configured(tmp_path, enable_live_apis=True)
    pipe = EvidencePipeline(cfg)
    install_sources(monkeypatch, {key: requests.Timeout("private") for key in LIVE_KEYS})
    previous = pipe.run("最新" + QUESTION)
    install_sources(monkeypatch, {key: [] for key in LIVE_KEYS})
    current = pipe.run("最新" + QUESTION)
    assert previous.degraded and not current.degraded
    assert all(previous.dependency_states[key].status == "error" for key in LIVE_KEYS)
    assert all(current.dependency_states[key].status == "empty" for key in LIVE_KEYS)
