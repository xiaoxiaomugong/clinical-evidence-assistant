import os
import time
import pytest
import requests

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


@pytest.mark.parametrize("retry_after, expected", [
    ("nan", .4), ("Infinity", .4), ("-3", 0), ("999999999999999999999", 5),
    ("not a date", .4), (None, .4),
    ("Thu, 01 Jan 1970 00:20:00 GMT", 5),
    ("Thu, 01 Jan 1970 00:16:42 GMT", 2),
    ("Thu, 01 Jan 1970 00:00:00 GMT", 0),
])
def test_retry_after_wait_is_finite_and_capped(monkeypatch, retry_after, expected):
    sleeps, attempts = [], []
    class FakeResponse:
        def __init__(self, status):
            self.status_code = status
            self.headers = {"Retry-After": retry_after}
    def get(*args, **kwargs):
        attempts.append(True)
        return FakeResponse(429 if len(attempts) == 1 else 200)
    monkeypatch.setattr(common.requests, "get", get)
    monkeypatch.setattr(common.time, "sleep", sleeps.append)
    monkeypatch.setattr(common.time, "time", lambda: 1000)
    response = common.get_with_retry("cap-test", "https://example.test", params={}, timeout=1,
                                     min_interval=0, max_attempts=2)
    assert response.status_code == 200 and sleeps == [expected]


def test_connection_backoff_respects_configured_cap(monkeypatch):
    sleeps = []
    def get(*args, **kwargs):
        raise requests.Timeout("unsafe message")
    monkeypatch.setattr(common.requests, "get", get)
    monkeypatch.setattr(common.time, "sleep", sleeps.append)
    with pytest.raises(requests.Timeout):
        common.get_with_retry("connection-test", "https://example.test", params={}, timeout=1,
                              min_interval=0, max_attempts=7, retry_sleep_cap_seconds=.5)
    assert sleeps == [.4, .5, .5, .5, .5, .5]


@pytest.mark.parametrize("cap", [float("nan"), float("inf"), -1])
def test_invalid_retry_cap_uses_finite_default(monkeypatch, cap):
    sleeps, attempts = [], []
    class FakeResponse:
        headers = {"Retry-After": "9999999999999999"}
        status_code = 429
    monkeypatch.setattr(common.requests, "get", lambda *a, **k: FakeResponse())
    monkeypatch.setattr(common.time, "sleep", sleeps.append)
    common.get_with_retry("invalid-cap-test", "https://example.test", params={}, timeout=1,
                          min_interval=0, max_attempts=2, retry_sleep_cap_seconds=cap)
    assert sleeps == [5.0]
