from pathlib import Path

import pytest

from evidence_assistant.retrievers.supabase import SupabaseCorpus, SupabaseDataAPI
from scripts.sync_supabase import upload


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


def test_stage_rows_wrap_payload_and_batches_by_run():
    session = FakeSession(FakeResponse(None), FakeResponse(None))
    api = SupabaseDataAPI(
        "https://project.supabase.co",
        "sb_secret_backend",
        session=session,
    )
    rows = [{"id": "pmid:1", "title": "one"}, {"id": "pmid:2", "title": "two"}]

    assert api.stage_rows(
        "evidence_document_staging", "run-1", rows, batch_size=1
    ) == 2

    assert [call[1].rsplit("/", 1)[-1] for call in session.calls] == [
        "evidence_document_staging",
        "evidence_document_staging",
    ]
    first_payload = session.calls[0][2]["json"][0]
    assert first_payload == {"run_id": "run-1", "id": "pmid:1", "payload": rows[0]}
    assert session.calls[0][2]["params"] == {"on_conflict": "run_id,id"}


def test_publish_and_abort_use_backend_only_rpcs():
    session = FakeSession(
        FakeResponse({"source_id": "pubmed_snapshot", "documents": 2, "chunks": 3}),
        FakeResponse(True),
    )
    api = SupabaseDataAPI(
        "https://project.supabase.co",
        "sb_secret_backend",
        session=session,
    )

    result = api.publish_ingestion("run-1")
    aborted = api.abort_ingestion("run-2", "upload failed")

    assert result["documents"] == 2
    assert aborted
    assert session.calls[0][1].endswith("/rpc/publish_evidence_ingestion")
    assert session.calls[0][2]["json"] == {"p_run_id": "run-1"}
    assert session.calls[1][1].endswith("/rpc/abort_evidence_ingestion")


class RecordingIngestionAPI:
    def __init__(self, fail_chunks=False):
        self.fail_chunks = fail_chunks
        self.calls = []

    def start_ingestion(self, source_id, metadata, records_seen=0):
        self.calls.append(("start", source_id, metadata, records_seen))
        return "run-1"

    def stage_rows(self, table, run_id, rows, batch_size):
        rows = list(rows)
        self.calls.append(("stage", table, run_id, rows, batch_size))
        if self.fail_chunks and table == "evidence_chunk_staging":
            raise RuntimeError("chunk upload failed")
        return len(rows)

    def publish_ingestion(self, run_id):
        self.calls.append(("publish", run_id))
        return {"source_id": "pubmed_snapshot", "documents": 1, "chunks": 1}

    def abort_ingestion(self, run_id, error_message):
        self.calls.append(("abort", run_id, error_message))
        return True


def test_upload_stages_all_batches_before_atomic_publish(capsys):
    api = RecordingIngestionAPI()

    upload(
        api,
        "pubmed_snapshot",
        [{"id": "pmid:1"}],
        [{"id": "pmid:1:chunk:1"}],
        batch_size=10,
    )

    assert [call[0] for call in api.calls] == ["start", "stage", "stage", "publish"]
    assert api.calls[0][2]["expected_chunks"] == 1
    assert api.calls[0][3] == 1
    assert "atomically" in capsys.readouterr().out


def test_failed_staging_aborts_without_publishing():
    api = RecordingIngestionAPI(fail_chunks=True)

    with pytest.raises(RuntimeError, match="chunk upload failed"):
        upload(
            api,
            "pubmed_snapshot",
            [{"id": "pmid:1"}],
            [{"id": "pmid:1:chunk:1"}],
            batch_size=10,
        )

    assert "publish" not in [call[0] for call in api.calls]
    assert api.calls[-1][0] == "abort"


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
    migration = (
        Path(__file__).parents[1]
        / "supabase"
        / "migrations"
        / "20260811073032_create_evidence_store.sql"
    )
    sql = migration.read_text(encoding="utf-8").lower()

    for table in ("source_catalog", "evidence_documents", "evidence_chunks", "ingestion_runs"):
        assert f"alter table public.{table} enable row level security" in sql
    assert "grant select on table public.evidence_documents to anon, authenticated" in sql
    assert "grant select on table public.evidence_chunks to anon, authenticated" in sql
    assert "grant execute on function public.search_evidence_chunks(text, integer)" in sql
    assert "grant insert on table public.evidence_documents to anon" not in sql
    assert "security invoker" in sql


def test_atomic_publish_migration_stages_then_replaces_a_source():
    migration = (
        Path(__file__).parents[1]
        / "supabase"
        / "migrations"
        / "20260812021056_atomic_evidence_publish.sql"
    )
    sql = migration.read_text(encoding="utf-8").lower()

    assert "create table public.evidence_document_staging" in sql
    assert "create table public.evidence_chunk_staging" in sql
    assert "alter table public.evidence_document_staging enable row level security" in sql
    assert "create or replace function public.publish_evidence_ingestion" in sql
    assert "security invoker" in sql
    assert "set is_active = false" in sql
    assert "delete from public.evidence_chunks" in sql
    assert "grant execute on function public.publish_evidence_ingestion(uuid)" in sql
    assert "to anon" not in sql.split(
        "grant execute on function public.publish_evidence_ingestion(uuid)", 1
    )[1].split(";", 1)[0]
