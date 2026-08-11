from pathlib import Path

from evidence_assistant.retrievers.supabase import SupabaseCorpus, SupabaseDataAPI


class FakeResponse:
    def __init__(self, data, status_code=200, headers=None):
        self._data = data
        self.status_code = status_code
        self.headers = headers or {}
        self.content = b"json"
        self.text = "fake response"

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def test_supabase_corpus_uses_publishable_key_without_bearer_header():
    session = FakeSession(
        FakeResponse(
            [
                {
                    "id": "pmid:1:chunk:1",
                    "doc_id": "pmid:1",
                    "source": "pubmed_snapshot",
                    "title": "Evidence title",
                    "text": "Evidence body",
                    "evidence_level": "RCT",
                    "url": "https://example.test/1",
                    "journal": "Journal",
                    "year": 2025,
                    "study_type": "Randomized Controlled Trial",
                    "status": "completed",
                    "topic": "hypertension",
                    "page_number": None,
                    "retrieval_score": 0.42,
                }
            ]
        )
    )
    corpus = SupabaseCorpus(
        "https://project.supabase.co",
        "sb_publishable_example",
        session=session,
    )

    results = corpus.search(["blood pressure"], top_k=5)

    assert results[0].doc_id == "pmid:1"
    assert results[0].retrieval_score == 0.42
    method, url, request = session.calls[0]
    assert method == "POST"
    assert url.endswith("/rest/v1/rpc/search_evidence_chunks")
    assert request["json"]["result_limit"] == 5
    assert request["headers"]["apikey"] == "sb_publishable_example"
    assert "Authorization" not in request["headers"]


def test_legacy_jwt_key_adds_bearer_header_and_reads_exact_count():
    session = FakeSession(FakeResponse([], headers={"Content-Range": "0-0/12"}))
    api = SupabaseDataAPI(
        "https://project.supabase.co",
        "eyJheader.payload.signature",
        session=session,
    )

    assert api.count_active_documents() == 12
    headers = session.calls[0][2]["headers"]
    assert headers["Authorization"] == "Bearer eyJheader.payload.signature"
    assert headers["Prefer"] == "count=exact"
    assert headers["Range"] == "0-0"


def test_upsert_batches_rows_and_requests_conflict_resolution():
    session = FakeSession(FakeResponse(None), FakeResponse(None), FakeResponse(None))
    api = SupabaseDataAPI(
        "https://project.supabase.co",
        "sb_secret_backend",
        session=session,
    )
    rows = [{"id": str(index)} for index in range(5)]

    assert api.upsert_rows("evidence_documents", rows, batch_size=2) == 5
    assert [len(call[2]["json"]) for call in session.calls] == [2, 2, 1]
    assert all(call[2]["params"] == {"on_conflict": "id"} for call in session.calls)
    assert all(
        call[2]["headers"]["Prefer"] == "resolution=merge-duplicates,return=minimal"
        for call in session.calls
    )


def test_document_download_uses_keyset_pagination():
    first_page = [
        {"id": "pmid:1"},
        {"id": "pmid:2"},
    ]
    session = FakeSession(FakeResponse(first_page), FakeResponse([]))
    api = SupabaseDataAPI(
        "https://project.supabase.co",
        "sb_publishable_example",
        session=session,
    )

    assert api.fetch_active_documents(page_size=2) == first_page
    assert "offset" not in session.calls[0][2]["params"]
    assert session.calls[1][2]["params"]["id"] == "gt.pmid:2"


def test_migration_enables_rls_and_keeps_writes_backend_only():
    migration = next((Path(__file__).parents[1] / "supabase" / "migrations").glob("*.sql"))
    sql = migration.read_text(encoding="utf-8").lower()

    for table in ("source_catalog", "evidence_documents", "evidence_chunks", "ingestion_runs"):
        assert f"alter table public.{table} enable row level security" in sql
    assert "grant select on table public.evidence_documents to anon, authenticated" in sql
    assert "grant select on table public.evidence_chunks to anon, authenticated" in sql
    assert "grant execute on function public.search_evidence_chunks(text, integer)" in sql
    assert "grant insert on table public.evidence_documents to anon" not in sql
    assert "security invoker" in sql
