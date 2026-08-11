import os
import time

from evidence_assistant.retrievers import common
from evidence_assistant.retrievers.clinicaltrials import _clinicaltrials_query
from evidence_assistant.schemas import Document
from evidence_assistant.query_rewrite import rewrite


def _document():
    return Document(
        id="pmid:1",
        source="pubmed",
        title="Test",
        abstract="Test abstract",
        evidence_level="Other",
        url="https://pubmed.ncbi.nlm.nih.gov/1/",
    )


def test_live_cache_expires(tmp_path):
    path = tmp_path / "cache.json"
    common.save_cache(path, [_document()])
    assert common.load_cache(path, max_age_seconds=60)

    old = time.time() - 120
    os.utime(path, (old, old))
    assert common.load_cache(path, max_age_seconds=60) is None


def test_get_with_retry_retries_rate_limit(monkeypatch):
    calls = []

    class FakeResponse:
        def __init__(self, status_code):
            self.status_code = status_code
            self.headers = {"Retry-After": "0"}

    def fake_get(url, params, headers, timeout):
        calls.append(url)
        return FakeResponse(429 if len(calls) == 1 else 200)

    monkeypatch.setattr(common.requests, "get", fake_get)
    response = common.get_with_retry(
        "test-source",
        "https://example.test",
        params={"q": "test"},
        timeout=1,
        min_interval=0,
        max_attempts=3,
    )

    assert response.status_code == 200
    assert len(calls) == 2


def test_clinicaltrials_query_quotes_hyphenated_terms():
    query = _clinicaltrials_query(rewrite("2型糖尿病 SGLT2 抑制剂证据"))

    assert '"glp-1"' in query
    assert " AND (" in query
