from __future__ import annotations

import hashlib
import importlib
import json
import shutil
import socket
import sqlite3
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from evidence_assistant.config import Settings
from scripts.index_pdf_collection import create_schema


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "runtime_diagnostics.py"


def diagnostics():
    assert SCRIPT.is_file(), "The administrator runtime diagnostics CLI is missing"
    return importlib.import_module("scripts.runtime_diagnostics")


@pytest.fixture
def cfg(tmp_path):
    root = tmp_path / "runtime"
    data = root / "data"
    shutil.copytree(ROOT / "data" / "knowledge_pages", data / "knowledge_pages")
    (data / "raw").mkdir()
    shutil.copy(ROOT / "data" / "raw" / "local_corpus.json", data / "raw")
    shutil.copy(ROOT / "data" / "corpus_version.json", data)
    return Settings(
        root_dir=root, data_dir=data, knowledge_dir=data / "knowledge_pages",
        local_corpus_path=data / "raw" / "local_corpus.json",
        pdf_index_path=data / "raw" / "optional.sqlite3",
        pdf_collection_dir=root / "optional-pdfs", vector_index_path=data / "indexes",
        cache_dir=root / "cache", retrieval_backend="legacy", rerank_backend="deterministic",
        embedding_model="", rerank_model="", corpus_version="v3",
        enable_live_apis=False, enable_supabase=False, llm_api_key="",
    )


def test_absent_optional_resources_and_git_are_ready(cfg):
    report = diagnostics().collect_diagnostics(cfg)

    assert report["status"] == "ready"
    assert report["build"]["commit"] == "unknown"
    assert report["resources"]["pdf_index"]["status"] == "absent_optional"
    assert report["resources"]["dense_index"]["status"] == "disabled"
    assert report["resources"]["rerank_model"]["status"] == "disabled"
    assert report["scope"] == "local_resources_only"
    assert report["external_dependencies_checked"] is False


def test_core_corpus_counts_and_snapshot_hash_come_from_files(cfg):
    report = diagnostics().collect_diagnostics(cfg)

    assert report["schema_version"] == "1.0"
    assert report["corpus"]["knowledge_pages"]["page_count"] == 5
    assert report["corpus"]["knowledge_pages"]["claim_count"] == 15
    assert report["corpus"]["snapshot"]["document_count"] == 10
    assert report["corpus"]["snapshot"]["sha256"] == hashlib.sha256(
        cfg.local_corpus_path.read_bytes()).hexdigest()
    assert report["corpus"]["version_manifest"]["matches_configuration"] is True
    cfg.local_corpus_path.write_text("[]", encoding="utf-8")
    changed = diagnostics().collect_diagnostics(cfg)
    assert changed["corpus"]["snapshot"]["document_count"] == 0
    assert changed["corpus"]["snapshot"]["sha256"] != report["corpus"]["snapshot"]["sha256"]
    assert changed["status"] == "not_ready"


@pytest.mark.parametrize("resource", ["knowledge", "snapshot"])
def test_missing_required_corpus_is_not_ready(cfg, resource):
    if resource == "knowledge":
        shutil.rmtree(cfg.knowledge_dir)
    else:
        cfg.local_corpus_path.unlink()

    report = diagnostics().collect_diagnostics(cfg)

    assert report["status"] == "not_ready"
    assert "core_corpus_unavailable" in report["reason_codes"]


@pytest.mark.parametrize("content", ["not JSON secret-raw-content", "{}", '[{"id": "only-id"}]'])
def test_invalid_snapshot_reports_validity_without_content(cfg, content):
    cfg.local_corpus_path.write_text(content, encoding="utf-8")

    report = diagnostics().collect_diagnostics(cfg)

    assert report["status"] == "not_ready"
    assert report["corpus"]["snapshot"]["status"] == "invalid"
    assert "secret-raw-content" not in json.dumps(report)


def test_invalid_knowledge_page_does_not_claim_ready(cfg):
    (cfg.knowledge_dir / "broken.json").write_text('{"id": "broken", "claims": []}')

    report = diagnostics().collect_diagnostics(cfg)

    assert report["status"] == "not_ready"
    assert report["corpus"]["knowledge_pages"]["status"] == "invalid"


def test_manifest_mismatch_is_degraded_and_never_echoes_version(cfg):
    secret = "synthetic-version-secret"
    (cfg.data_dir / "corpus_version.json").write_text(json.dumps({"version": secret}))

    report = diagnostics().collect_diagnostics(cfg)

    assert report["status"] == "degraded"
    assert report["corpus"]["version_manifest"]["matches_configuration"] is False
    assert secret not in json.dumps(report)


def test_configuration_allowlist_omits_secrets_urls_models_paths_and_unknown_fields(cfg):
    secret = "synthetic-credential-DO-NOT-LOG"
    payload = dict(cfg.__dict__)
    payload.update(
        llm_api_key=secret, llm_base_url="https://user:" + secret + "@example.test/v1",
        llm_model=secret, pubmed_api_key=secret, ncbi_email=secret,
        embedding_model=secret, embedding_model_revision=secret, rerank_model=secret,
        rerank_model_revision=secret, supabase_secret_key=secret,
        supabase_publishable_key=secret, supabase_url="https://example.test/" + secret,
        arbitrary_future_field=secret, corpus_version=secret,
    )
    cfg_with_unknown = SimpleNamespace(**payload)

    report = diagnostics().collect_diagnostics(cfg_with_unknown)

    encoded = json.dumps(report)
    assert secret not in encoded
    assert str(cfg.root_dir) not in encoded
    assert "example.test" not in encoded
    assert "arbitrary_future_field" not in report["configuration"]
    assert report["configuration"]["candidate_pool_policy"] == "source_preserving"
    assert report["configuration"]["generation_top_k"] == 5


@pytest.mark.parametrize("value", ["secret-invalid-policy", "https://secret.example/path"])
def test_unknown_enum_values_are_redacted_and_not_ready(cfg, value):
    report = diagnostics().collect_diagnostics(replace(cfg, candidate_pool_policy=value))

    assert report["status"] == "not_ready"
    assert report["configuration"]["candidate_pool_policy"] == "invalid"
    assert value not in json.dumps(report)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 10 ** 400])
def test_invalid_numeric_configuration_is_not_ready_and_json_safe(cfg, value):
    report = diagnostics().collect_diagnostics(replace(cfg, request_timeout=value))

    assert report["status"] == "not_ready"
    assert report["configuration"]["request_timeout"] is None
    json.dumps(report, allow_nan=False)


def test_present_pdf_index_is_inspected_without_mutation(cfg):
    with sqlite3.connect(str(cfg.pdf_index_path)) as connection:
        create_schema(connection)
        connection.execute(
            "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("pmid:1", "1", "Title", "Abstract", "Journal", 2024, "[]", "RCT", "RCT",
             "https://example.test/secret", "Topic", "private.pdf", 1, 1, "full_text", None),
        )
        connection.execute("INSERT INTO chunks VALUES ('c1', 'pmid:1', 1, 'Content')")
        connection.execute("INSERT INTO chunk_fts VALUES ('c1', 'pmid:1', 'Title', 'Content')")
    before = cfg.pdf_index_path.read_bytes()

    report = diagnostics().collect_diagnostics(cfg)

    pdf = report["resources"]["pdf_index"]
    assert pdf["status"] == "valid"
    assert pdf["document_count"] == 1
    assert pdf["chunk_count"] == 1
    assert pdf["sha256"] == hashlib.sha256(before).hexdigest()
    assert cfg.pdf_index_path.read_bytes() == before
    assert "private.pdf" not in json.dumps(report)
    assert "example.test" not in json.dumps(report)


def test_corrupt_optional_pdf_degrades_without_exposing_error(cfg):
    cfg.pdf_index_path.write_text("synthetic-pdf-secret")

    report = diagnostics().collect_diagnostics(cfg)

    assert report["status"] == "degraded"
    assert report["resources"]["pdf_index"]["status"] == "invalid"
    assert "synthetic-pdf-secret" not in json.dumps(report)


def test_pdf_with_incomplete_search_schema_is_invalid(cfg):
    with sqlite3.connect(str(cfg.pdf_index_path)) as connection:
        connection.executescript("""
            CREATE TABLE documents (id TEXT PRIMARY KEY);
            CREATE TABLE chunks (id TEXT PRIMARY KEY, doc_id TEXT);
            CREATE TABLE chunk_fts (chunk_id TEXT, doc_id TEXT);
            INSERT INTO documents VALUES ('d1');
            INSERT INTO chunks VALUES ('c1', 'd1');
            INSERT INTO chunk_fts VALUES ('c1', 'd1');
        """)

    report = diagnostics().collect_diagnostics(cfg)

    assert report["status"] == "degraded"
    assert report["resources"]["pdf_index"]["status"] == "invalid"


@pytest.mark.parametrize("chunk_count,fts_identities", [
    (1, [("nonexistent-private-fts-id", "pmid:1")]),
    (1, [("c1", "pmid:2")]),
    (2, [("c1", "pmid:1"), ("c1", "pmid:1")]),
    (2, [("c1", "pmid:1"), ("nonexistent-private-fts-id", "pmid:1")]),
])
def test_pdf_fts_identity_mismatch_is_invalid_even_when_counts_match(cfg, chunk_count, fts_identities):
    with sqlite3.connect(str(cfg.pdf_index_path)) as connection:
        create_schema(connection)
        for number in (1, 2):
            connection.execute(
                "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("pmid:%s" % number, str(number), "Title", "Abstract", "Journal", 2024,
                 "[]", "RCT", "RCT", "https://example.test/secret", "Topic",
                 "private.pdf", 1, 1, "full_text", None),
            )
        for number in range(1, chunk_count + 1):
            connection.execute("INSERT INTO chunks VALUES (?, 'pmid:1', 1, 'Content')", ("c%s" % number,))
        for chunk_id, doc_id in fts_identities:
            connection.execute("INSERT INTO chunk_fts VALUES (?, ?, 'Title', 'Content')", (chunk_id, doc_id))
        assert connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == chunk_count
        assert connection.execute("SELECT COUNT(*) FROM chunk_fts").fetchone()[0] == chunk_count
    before = cfg.pdf_index_path.read_bytes()
    paths_before = sorted(cfg.pdf_index_path.parent.iterdir())

    report = diagnostics().collect_diagnostics(cfg)

    assert report["status"] == "degraded"
    assert report["resources"]["pdf_index"]["status"] == "invalid"
    assert cfg.pdf_index_path.read_bytes() == before
    assert sorted(cfg.pdf_index_path.parent.iterdir()) == paths_before
    assert "nonexistent-private-fts-id" not in json.dumps(report)


def test_pdf_search_table_must_use_fts5(cfg):
    with sqlite3.connect(str(cfg.pdf_index_path)) as connection:
        create_schema(connection)
        connection.execute("DROP TABLE chunk_fts")
        connection.execute("CREATE VIRTUAL TABLE chunk_fts USING fts4(chunk_id, doc_id, title, text)")
        connection.execute(
            "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("pmid:1", "1", "Title", "Abstract", "Journal", 2024, "[]", "RCT", "RCT",
             "https://example.test/secret", "Topic", "private.pdf", 1, 1, "full_text", None),
        )
        connection.execute("INSERT INTO chunks VALUES ('c1', 'pmid:1', 1, 'Content')")
        connection.execute("INSERT INTO chunk_fts VALUES ('c1', 'pmid:1', 'Title', 'Content')")
    before = cfg.pdf_index_path.read_bytes()

    report = diagnostics().collect_diagnostics(cfg)

    assert report["status"] == "degraded"
    assert report["resources"]["pdf_index"]["status"] == "invalid"
    assert cfg.pdf_index_path.read_bytes() == before


def test_pdf_with_wal_is_unverified_and_does_not_create_sidecars(cfg):
    cfg.pdf_index_path.write_bytes(b"synthetic-index")
    wal = Path(str(cfg.pdf_index_path) + "-wal")
    wal.write_bytes(b"synthetic-wal")
    before = sorted(cfg.pdf_index_path.parent.iterdir())

    report = diagnostics().collect_diagnostics(cfg)

    assert report["status"] == "degraded"
    assert report["resources"]["pdf_index"]["status"] == "unverified_wal"
    assert sorted(cfg.pdf_index_path.parent.iterdir()) == before
    assert wal.read_bytes() == b"synthetic-wal"


def test_enabled_dense_with_missing_index_is_degraded(cfg):
    report = diagnostics().collect_diagnostics(replace(
        cfg, retrieval_backend="hybrid", embedding_model="private-missing-model"))

    assert report["status"] == "degraded"
    assert report["resources"]["dense_index"]["status"] == "missing"
    assert report["resources"]["dense_index"]["inference_checked"] is False
    assert "private-missing-model" not in json.dumps(report)


def test_dense_artifact_is_validated_but_inference_remains_unverified(cfg):
    np = pytest.importorskip("numpy")
    from evidence_assistant.index_registry import IndexRegistry
    from evidence_assistant.schemas import Chunk
    model = cfg.root_dir / "local-model"
    model.mkdir()
    dense_cfg = replace(cfg, retrieval_backend="dense", embedding_model=str(model),
                        embedding_model_revision="test-revision")
    target = IndexRegistry(cfg.vector_index_path).write(
        "v3", str(model), "test-revision",
        [Chunk("c1", "d1", "knowledge_page", "Title", "Text", "RCT")],
        np.array([[1.0, 0.0]], dtype=np.float32),
    )
    before = {path.name: path.read_bytes() for path in target.iterdir()}

    report = diagnostics().collect_diagnostics(dense_cfg)

    dense = report["resources"]["dense_index"]
    assert dense["status"] == "valid"
    assert dense["item_count"] == 1
    assert dense["model_artifact"] == "present_unverified"
    assert dense["inference_checked"] is False
    assert report["status"] == "degraded"
    assert {path.name: path.read_bytes() for path in target.iterdir()} == before
    (target / "records.jsonl").write_text("synthetic-invalid-dense-secret")
    invalid = diagnostics().collect_diagnostics(dense_cfg)
    assert invalid["resources"]["dense_index"]["status"] == "invalid"
    assert "synthetic-invalid-dense-secret" not in json.dumps(invalid)


def test_scalar_dense_array_is_invalid_and_cli_redacts_shape_failure(cfg, tmp_path):
    np = pytest.importorskip("numpy")
    from evidence_assistant.index_registry import IndexRegistry
    from evidence_assistant.schemas import Chunk
    model = cfg.root_dir / "synthetic-private-model-directory"
    model.mkdir()
    dense_cfg = replace(cfg, retrieval_backend="dense", embedding_model=str(model),
                        embedding_model_revision="test-revision")
    target = IndexRegistry(cfg.vector_index_path).write(
        "v3", str(model), "test-revision",
        [Chunk("c1", "d1", "knowledge_page", "Title", "Text", "RCT")],
        np.array([[1.0, 0.0]], dtype=np.float32),
    )
    np.save(str(target / "embeddings.npy"), np.array(1.0), allow_pickle=False)
    before = {path.name: path.read_bytes() for path in target.iterdir()}

    report = diagnostics().collect_diagnostics(dense_cfg)

    assert report["status"] == "degraded"
    assert report["resources"]["dense_index"]["status"] == "invalid"
    assert "dense_index_unavailable" in report["reason_codes"]
    assert "synthetic-private-model-directory" not in json.dumps(report)
    assert str(target) not in json.dumps(report)
    assert {path.name: path.read_bytes() for path in target.iterdir()} == before
    import os
    env = dict(os.environ)
    env.update(CLINICAL_EVIDENCE_ROOT=str(cfg.root_dir), EVIDENCE_ASSISTANT_DATA_DIR=str(cfg.data_dir),
               KNOWLEDGE_DIR=str(cfg.knowledge_dir), LOCAL_CORPUS_PATH=str(cfg.local_corpus_path),
               PDF_INDEX_PATH=str(cfg.pdf_index_path), VECTOR_INDEX_PATH=str(cfg.vector_index_path),
               CORPUS_VERSION="v3", RETRIEVAL_BACKEND="dense", RERANK_BACKEND="deterministic",
               EMBEDDING_MODEL=str(model), EMBEDDING_MODEL_REVISION="test-revision")
    output = tmp_path / "scalar-index-report.json"
    completed = subprocess.run([sys.executable, str(SCRIPT), "--output", str(output)],
                               capture_output=True, text=True, env=env)
    assert completed.returncode == 0
    cli_report = json.loads(output.read_text())
    assert cli_report["resources"]["dense_index"]["status"] == "invalid"
    assert cli_report["status"] == "degraded"
    visible = completed.stdout + completed.stderr + output.read_text()
    assert "Traceback" not in visible
    assert "IndexError" not in visible
    assert "synthetic-private-model-directory" not in visible
    assert str(target) not in visible
    assert {path.name: path.read_bytes() for path in target.iterdir()} == before


def test_missing_required_package_cannot_claim_ready(cfg, monkeypatch):
    module = diagnostics()
    original = module.metadata.version

    def version(name):
        if name == "streamlit":
            raise module.metadata.PackageNotFoundError(name)
        return original(name)

    monkeypatch.setattr(module.metadata, "version", version)

    report = module.collect_diagnostics(cfg)

    assert report["status"] == "not_ready"
    assert report["runtime"]["packages"]["streamlit"] is None
    assert "required_package_missing" in report["reason_codes"]


def test_diagnostics_never_connects_or_creates_runtime_directories(cfg, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("runtime diagnostics must not perform network operations")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    before = sorted(str(path.relative_to(cfg.root_dir)) for path in cfg.root_dir.rglob("*"))

    report = diagnostics().collect_diagnostics(cfg)

    after = sorted(str(path.relative_to(cfg.root_dir)) for path in cfg.root_dir.rglob("*"))
    assert report["status"] == "ready"
    assert before == after
    assert not cfg.cache_dir.exists()
    assert not cfg.vector_index_path.exists()


def test_package_versions_are_reported_without_importing_optional_models(cfg):
    was_loaded = "sentence_transformers" in sys.modules
    report = diagnostics().collect_diagnostics(cfg)

    assert report["runtime"]["python_version"] == "%s.%s.%s" % sys.version_info[:3]
    assert report["runtime"]["packages"]["pytest"]
    assert report["runtime"]["packages"]["streamlit"]
    assert ("sentence_transformers" in sys.modules) is was_loaded


def test_cli_writes_a_new_report_and_refuses_overwrite(tmp_path):
    output = tmp_path / "new-report.json"
    command = [sys.executable, str(SCRIPT), "--output", str(output)]

    first = subprocess.run(command, capture_output=True, text=True)

    assert first.returncode == 0, first.stderr
    report = json.loads(output.read_text())
    assert report["status"] == "ready"
    before = output.read_bytes()
    repeated = subprocess.run(command, capture_output=True, text=True)
    assert repeated.returncode == 2
    assert output.read_bytes() == before
    assert str(output) not in repeated.stderr


def test_cli_uses_discovered_data_and_returns_nonzero_for_not_ready(cfg, tmp_path):
    output = tmp_path / "not-ready.json"
    cfg.local_corpus_path.unlink()
    import os
    env = dict(os.environ)
    env.update(CLINICAL_EVIDENCE_ROOT=str(cfg.root_dir), EVIDENCE_ASSISTANT_DATA_DIR=str(cfg.data_dir),
               KNOWLEDGE_DIR=str(cfg.knowledge_dir), LOCAL_CORPUS_PATH=str(cfg.local_corpus_path),
               PDF_INDEX_PATH=str(cfg.pdf_index_path), RETRIEVAL_BACKEND="legacy", RERANK_BACKEND="deterministic")

    completed = subprocess.run([sys.executable, str(SCRIPT), "--output", str(output)],
                               capture_output=True, text=True, env=env)

    assert completed.returncode == 1
    assert json.loads(output.read_text())["status"] == "not_ready"
    assert str(cfg.root_dir) not in completed.stdout + completed.stderr


def test_cli_redacts_invalid_environment_configuration(tmp_path):
    import os
    env = dict(os.environ, API_REQUEST_TIMEOUT="synthetic-invalid-timeout-secret")
    output = tmp_path / "invalid-config.json"

    completed = subprocess.run([sys.executable, str(SCRIPT), "--output", str(output)],
                               capture_output=True, text=True, env=env)

    assert completed.returncode == 1
    assert json.loads(output.read_text())["status"] == "not_ready"
    assert "synthetic-invalid-timeout-secret" not in completed.stdout + completed.stderr + output.read_text()
