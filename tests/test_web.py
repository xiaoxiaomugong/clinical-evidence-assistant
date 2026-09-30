"""Public API boundaries: local execution, privacy, citations and concurrency."""
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient


@pytest.fixture
def web():
    from evidence_assistant import web
    return web


@pytest.fixture
def client(web):
    with TestClient(web.create_app()) as client:
        yield client


def _result(text="成人高血压需要定期复评。", number=7, **changes):
    from evidence_assistant.schemas import Answer, AnswerParagraph, Entry, PipelineResult
    entry = Entry(id="pmid:34775787:chunk:1", doc_id="pmid:34775787",
                  source="pubmed_snapshot", title="Public source", text=text,
                  evidence_level="Guideline", url="https://pubmed.ncbi.nlm.nih.gov/34775787/",
                  citation_number=number, year=2022)
    result = PipelineResult(question="private-question", mode="hybrid",
                            answer=Answer(refused=False, paragraphs=[AnswerParagraph(text, [number])]),
                            entries=[entry], citation_check=None,
                            generation_entry_ids=[entry.id], trace=["/private/secret.env"])
    for key, value in changes.items():
        setattr(result, key, value)
    return result


class Pipeline:
    def __init__(self, result=None, error=None):
        self.result = result or _result()
        self.error = error
        self.calls = []

    def run(self, question, *, mode, enable_live_apis):
        self.calls.append((question, mode, enable_live_apis))
        if self.error:
            raise self.error
        return self.result


def test_real_answer_uses_local_supported_sources(client):
    response = client.post("/api/v1/queries", json={"question": "降压药应早上服用还是睡前服用？", "audience": "public"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "answered"
    assert payload["generation_method"] == "extractive"
    assert payload["online_search"] is False
    sources = {source["id"]: source for source in payload["sources"]}
    assert sources
    for claim in payload["answer"]["claims"]:
        assert claim["citations"]
        assert all(number in sources for number in claim["citations"])
    assert all(source["source_type"] in {"knowledge_page", "pubmed_snapshot"} for source in sources.values())
    assert response.headers["cache-control"] == "no-store"
    assert set(payload) == {"request_id", "audience", "status", "degraded", "generation_method", "message", "answer", "sources", "corpus", "online_search"}


@pytest.mark.parametrize("body", [
    {"question": "", "audience": "public"},
    {"question": " " * 5, "audience": "public"},
    {"question": "x" * 2001, "audience": "public"},
    {"question": "private-question", "audience": "private"},
    {"question": "private-question", "audience": "public", "enable_live_apis": True},
    {"question": "private-question", "audience": "professional", "pico": {"population": "x" * 501}},
    {"question": "private-question", "audience": "professional", "pico": {"secret": "value"}},
    {"question": "x" * 2000, "audience": "professional", "pico": dict.fromkeys(["population", "intervention", "comparison", "outcome"], "x" * 500)},
])
def test_validation_never_echoes_body(web, body):
    pipeline = Pipeline()
    with TestClient(web.create_app(pipeline=pipeline)) as client:
        response = client.post("/api/v1/queries", json=body)
    assert response.status_code == 422
    assert "private-question" not in response.text
    assert "input" not in response.text
    assert pipeline.calls == []
    assert response.headers["cache-control"] == "no-store"


def test_malformed_json_and_large_body_are_safe(client):
    invalid = client.post("/api/v1/queries", content='{"question":"private-question",', headers={"content-type": "application/json"})
    assert invalid.status_code == 422
    assert "private-question" not in invalid.text
    large = client.post("/api/v1/queries", content=b"x" * 65537, headers={"content-type": "application/json"})
    assert large.status_code == 413
    assert large.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("field", ["population", "intervention", "comparison", "outcome"])
def test_phi_in_each_pico_field_is_blocked_before_pipeline(web, field, caplog):
    pipeline = Pipeline()
    with TestClient(web.create_app(pipeline=pipeline)) as client:
        response = client.post("/api/v1/queries", json={"question": "成人高血压证据", "audience": "professional", "pico": {field: "病历号 PRIVATE1234"}})
    assert response.status_code == 200
    assert response.json()["status"] == "refused"
    assert response.json()["answer"] is None
    assert response.json()["sources"] == []
    assert "PRIVATE1234" not in response.text + caplog.text
    assert pipeline.calls == []


def test_pico_is_combined_with_question_for_real_retrieval(web):
    pipeline = Pipeline()
    with TestClient(web.create_app(pipeline=pipeline)) as client:
        response = client.post("/api/v1/queries", json={"question": "成人高血压证据", "audience": "professional", "pico": {"population": "非妊娠成人", "intervention": "早晨服药", "comparison": "睡前服药", "outcome": "心血管结局"}})
    assert response.status_code == 200
    question, mode, live = pipeline.calls[0]
    assert all(value in question for value in ["成人高血压证据", "非妊娠成人", "早晨服药", "睡前服药", "心血管结局"])
    assert mode == "hybrid" and live is False


@pytest.mark.parametrize("question", ["姓名：张三，成人高血压有什么证据？", "我需要停药吗？", "宠物狗高血压怎么办？"])
def test_safety_refusals_have_no_question_or_sources(client, question):
    response = client.post("/api/v1/queries", json={"question": question, "audience": "public"})
    assert response.status_code == 200
    assert response.json()["status"] == "refused"
    assert response.json()["answer"] is None
    assert response.json()["sources"] == []
    assert question not in response.text


def test_projection_rechecks_support_preserves_numbers_and_hides_internal_fields(web):
    from evidence_assistant.schemas import AnswerParagraph
    result = _result(degraded=True, degradation_reasons=["secret.env"])
    result.answer.paragraphs.append(AnswerParagraph("完全不存在的治疗能治愈全部疾病。", [7, 99]))
    result.answer.reason = "private-reason"
    result.answer.limitations = ["private-limitation"]
    with TestClient(web.create_app(pipeline=Pipeline(result))) as client:
        payload = client.post("/api/v1/queries", json={"question": "高血压证据", "audience": "public"}).json()
    assert payload["status"] == "answered" and payload["degraded"] is True
    assert payload["answer"]["claims"] == [{"text": "成人高血压需要定期复评。", "citations": [7]}]
    assert [source["id"] for source in payload["sources"]] == [7]
    assert payload["sources"][0]["identifiers"] == {"pmid": "34775787"}
    assert payload["sources"][0]["evidence_level"] == "Guideline"
    assert payload["sources"][0]["study_type"] is None
    assert payload["sources"][0]["publication_status"] is None
    serialized = json.dumps(payload, ensure_ascii=False)
    assert all(secret not in serialized for secret in ["private-question", "private-reason", "private-limitation", "secret.env", "完全不存在", "generation_entry_ids", "trace"])


def test_unsafe_source_links_are_never_exposed(web):
    result = _result()
    result.entries[0].url = "javascript:alert('secret')"
    with TestClient(web.create_app(pipeline=Pipeline(result))) as client:
        response = client.post("/api/v1/queries", json={"question": "高血压证据", "audience": "public"})
    assert "javascript" not in response.text
    assert all(source["url"] is None for source in response.json()["sources"])


def test_exception_returns_safe_503_and_logs_no_exception_or_body(web, caplog):
    with TestClient(web.create_app(pipeline=Pipeline(error=RuntimeError("private-question /tmp/secret.env")))) as client:
        response = client.post("/api/v1/queries", json={"question": "高血压证据", "audience": "public"})
    assert response.status_code == 503
    assert response.json()["status"] == "error"
    assert response.json()["answer"] is None
    assert "private-question" not in response.text + caplog.text
    assert "secret.env" not in response.text + caplog.text


def test_topics_have_real_unreviewed_metadata(client):
    response = client.get("/api/v1/topics")
    assert response.status_code == 200
    topics = response.json()["topics"]
    assert len(topics) == 5
    for topic in topics:
        assert topic["review_status"] == "未记录" and topic["reviewer"] is None
        detail = client.get("/api/v1/topics/" + topic["id"]).json()
        assert len(detail["content"]) >= 3 and detail["references"]
        assert detail["updated_at"] == "2026-08-11"
    assert client.get("/api/v1/topics/not-found").status_code == 404
    assert response.json()["corpus"] == {"version": "v3", "updated_at": "2026-08-11"}


def test_health_is_minimal_and_ready_with_real_corpus(client):
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").json() == {"status": "ready"}


def test_openapi_documents_only_public_query_fields(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert set(schema["components"]["schemas"]["QueryInput"]["properties"]) == {"question", "audience", "pico"}
    assert set(schema["components"]["schemas"]["QueryResponse"]["properties"]) == {"request_id", "audience", "status", "degraded", "generation_method", "message", "answer", "sources", "corpus", "online_search"}
    assert client.get("/docs").status_code == 404


def test_missing_corpus_fails_ready_and_query_without_path_disclosure(web, tmp_path, monkeypatch):
    monkeypatch.setattr(web, "_resource_root", lambda: tmp_path)
    with TestClient(web.create_app()) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 503
        response = client.post("/api/v1/queries", json={"question": "高血压证据", "audience": "public"})
    assert response.status_code == 503
    assert response.json()["status"] == "error"
    assert str(tmp_path) not in response.text


def test_long_source_text_is_exposed_only_as_excerpt(web):
    result = _result(text="成人高血压需要定期复评。" * 100)
    with TestClient(web.create_app(pipeline=Pipeline(result))) as client:
        response = client.post("/api/v1/queries", json={"question": "高血压证据", "audience": "public"})
    assert response.json()["status"] == "answered"
    assert len(response.json()["sources"][0]["excerpt"]) <= 800


def test_run_and_projection_share_one_serial_lock(web, monkeypatch):
    first_projection = Event()
    second_attempt = Event()
    release_projection = Event()
    pipeline = Pipeline()
    original_project = web._project_result

    def project(*args, **kwargs):
        if not first_projection.is_set():
            first_projection.set()
            assert release_projection.wait(3)
        return original_project(*args, **kwargs)

    monkeypatch.setattr(web, "_project_result", project)
    app = web.create_app(pipeline=pipeline)
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as executor:
        def submit():
            second_attempt.set()
            return client.post("/api/v1/queries", json={"question": "高血压证据", "audience": "public"})
        first = executor.submit(submit)
        assert first_projection.wait(3)
        second_attempt.clear()
        second = executor.submit(submit)
        assert second_attempt.wait(3)
        time.sleep(0.05)
        calls_during_projection = len(pipeline.calls)
        release_projection.set()
        assert first.result().status_code == second.result().status_code == 200
    assert calls_during_projection == 1


@pytest.mark.parametrize("questions,statuses", [
    (["降压药应早上服用还是睡前服用？", "饮食模式和钠摄入与心血管风险有哪些现有证据？"], ["answered", "answered"]),
    (["姓名：张三，病历号 PRIVATE1234，高血压证据", "降压药应早上服用还是睡前服用？"], ["refused", "answered"]),
])
def test_concurrent_real_requests_preserve_each_serial_answer(client, questions, statuses):
    def submit(question):
        response = client.post("/api/v1/queries", json={"question": question, "audience": "public"})
        assert response.status_code == 200
        return response.json()

    baseline = [submit(question) for question in questions]
    barrier = Barrier(2)

    def concurrent(question):
        barrier.wait(timeout=3)
        return submit(question)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(concurrent, questions))
    assert [result["status"] for result in results] == statuses
    for serial, parallel in zip(baseline, results):
        assert parallel["answer"] == serial["answer"]
        assert parallel["sources"] == serial["sources"]
        assert parallel["degraded"] == serial["degraded"]
    assert len({result["request_id"] for result in baseline + results}) == 4
    assert results[0]["answer"] != results[1]["answer"]


@pytest.mark.parametrize("preimport", [False, True])
def test_import_and_factory_ignore_host_environment_and_dotenv(tmp_path, preimport):
    code = """
import dotenv, requests
def blocked(*a, **k): raise AssertionError('external access')
PREIMPORT
dotenv.load_dotenv = blocked
requests.sessions.Session.request = blocked
from evidence_assistant.web import create_app
from fastapi.testclient import TestClient
with TestClient(create_app()) as client:
    p = client.post('/api/v1/queries', json={'question':'降压药应早上服用还是睡前服用？','audience':'public'}).json()
    assert p['status'] == 'answered', p
    assert p['generation_method'] == 'extractive'
    assert p['online_search'] is False
"""
    preimport_code = """
dotenv.load_dotenv = lambda *a, **k: None
import evidence_assistant.config as existing_config
assert existing_config.settings.enable_live_apis is True
assert existing_config.settings.llm_api_key == 'synthetic-secret'
""" if preimport else ""
    code = code.replace("PREIMPORT", preimport_code)
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"),
               RETRIEVE_K="40" if preimport else "not-an-integer", ENABLE_LIVE_APIS="true", ENABLE_SUPABASE="true",
               LLM_API_KEY="synthetic-secret", LLM_BASE_URL="http://127.0.0.1:1",
               RETRIEVAL_BACKEND="hybrid", RERANK_BACKEND="cross_encoder", MODEL_LOCAL_FILES_ONLY="false",
               CLINICAL_EVIDENCE_ROOT=str(tmp_path), KNOWLEDGE_DIR=str(tmp_path),
               LOCAL_CORPUS_PATH=str(tmp_path / "missing"), PDF_INDEX_PATH=str(tmp_path / "private.sqlite3"))
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_web_settings_ignore_preimported_config_and_disable_pdf(web, monkeypatch):
    from dataclasses import replace
    import evidence_assistant.config as config
    import evidence_assistant.pipeline as engine
    monkeypatch.setattr(config, "settings", replace(config.settings, llm_api_key="synthetic", enable_live_apis=True, enable_supabase=True))
    monkeypatch.setattr(engine.PdfCorpus, "search", lambda *a, **k: pytest.fail("local PDF accessed"))
    monkeypatch.setattr(engine, "pubmed_search", lambda *a, **k: pytest.fail("external API accessed"))
    with TestClient(web.create_app()) as client:
        response = client.post("/api/v1/queries", json={"question": "降压药应早上服用还是睡前服用？", "audience": "public"})
    assert response.json()["status"] == "answered"
