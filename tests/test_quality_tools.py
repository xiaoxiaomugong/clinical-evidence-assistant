from scripts.audit_corpus import audit
from scripts.lint_knowledge_pages import lint
from config import settings
import json
import sqlite3
import subprocess
import sys
import hashlib
import pytest

from scripts.index_pdf_collection import create_schema


def make_index(path, records):
    with sqlite3.connect(str(path)) as connection:
        create_schema(connection)
        for number, record in enumerate(records, 1):
            title = record.get("title", "Study title %s" % number)
            text = record.get("text", "Adults were followed for clinical outcomes. " * 20)
            connection.execute(
                "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("pmid:%s" % number, str(number), title, record.get("abstract", text), "Journal", 2024,
                 "[]", "Journal Article", record.get("level", "RCT"), "https://pubmed.ncbi.nlm.nih.gov/%s/" % number,
                 record.get("topic", "高血压"), "missing.pdf", 1, 3,
                 record.get("status", "full_text"), None),
            )
            if text:
                connection.execute("INSERT INTO chunks VALUES (?, ?, ?, ?)",
                                   ("c%s" % number, "pmid:%s" % number, 1, text))
                connection.execute("INSERT INTO chunk_fts VALUES (?, ?, ?, ?)",
                                   ("c%s" % number, "pmid:%s" % number, title, text))


def complete_manifest(path):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with sqlite3.connect(str(path)) as connection:
        connection.row_factory = sqlite3.Row
        rows = list(connection.execute("SELECT * FROM documents ORDER BY id"))
    return {"schema_version": "1.0", "corpus_version": "test-v1", "parser_version": "test-parser-v1",
            "created_at": "2026-09-21T00:00:00+00:00", "snapshot_method": "synthetic_fixture",
            "source_checksums_before": {str(path): digest}, "source_checksums_after": {str(path): digest},
            "source_unchanged": True, "index_sha256": digest, "records": [
        {"canonical_source_id": row["id"], "identity_status": "verified_title",
         "content_status": row["extraction_status"], "topic": row["topic"], "evidence_level": row["evidence_level"],
         "classification_basis": ["Randomized Controlled Trial"], "classification_review_status": "metadata_mapped",
         "source_url": row["url"], "acquired_at": "unknown", "authorization": "unknown", "permitted_use": "unknown",
         "file_sha256": "a" * 64, "metadata_sha256": "b" * 64, "parser_version": "test-parser-v1",
         "pdf_identity_evidence": {"method": "exact_complete_prominent_header_title", "page": 1,
                                   "bbox": [40, 40, 500, 100], "body_font_size": 10,
                                   "minimum_title_font_size": 10.8, "before_section_boundary_y": 170},
         "anomaly_reasons": [], "disposition": "retained", "index_version": "test-v1"} for row in rows]}


def test_corpus_audit_reports_bundled_assets():
    report = audit(settings.pdf_index_path)

    assert report["bundled"]["knowledge_pages"] >= 5
    assert report["bundled"]["knowledge_claims"] >= 15
    assert "quality_gates" in report


def test_current_knowledge_pages_have_no_schema_errors():
    issues = lint(settings.knowledge_dir)

    assert not [issue for issue in issues if issue["level"] == "error"]


def test_title_only_and_unindexed_abstracts_do_not_inflate_usable_counts(tmp_path):
    path = tmp_path / "corpus.sqlite3"
    make_index(path, [
        {"level": "Other"},
        {"status": "abstract_fallback", "title": "Title only", "text": "Title only", "abstract": "", "level": "Other"},
        {"status": "abstract_fallback", "text": "", "abstract": "Substantive abstract. " * 30},
        {"status": "abstract_fallback", "level": "Review"},
    ])
    report = audit(path)
    assert report["pdf_index"]["all_records"]["documents"] == 4
    assert report["pdf_index"]["usable_records"]["documents"] == 2
    assert report["pdf_index"]["usable_records"]["evidence_levels"] == {"Other": 1, "Review": 1}
    assert report["pdf_index"]["title_only"] == 1
    assert report["pdf_index"]["abstract_fallback"] == 1
    assert report["quality_gates"]["other_evidence_level_below_50_percent"] is False


def test_quality_gates_use_strict_boundaries_and_manifest_identity(tmp_path):
    path = tmp_path / "corpus.sqlite3"
    topics = ["高血压", "血脂", "糖尿病", "脑卒中", "心脑血管"]
    make_index(path, [{"level": "Other" if n < 249 else "RCT", "topic": topics[n % 5],
                       "status": "full_text" if n < 450 else "abstract_fallback"} for n in range(500)])
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(complete_manifest(path)))
    report = audit(path, manifest_path=manifest)
    assert all(report["quality_gates"].values())
    with sqlite3.connect(str(path)) as connection:
        connection.execute("UPDATE documents SET evidence_level = 'Other' WHERE pmid = '250'")
        connection.execute("INSERT INTO chunks VALUES ('orphan', 'pmid:missing', 1, 'orphan content')")
    report = audit(path, manifest_path=manifest)
    assert report["quality_gates"]["other_evidence_level_below_50_percent"] is False
    assert report["quality_gates"]["no_orphan_chunks"] is False
    assert report["pdf_index"]["integrity_check"] == ["ok"]
    manifest.write_text(json.dumps({"records": [{"canonical_source_id": "pmid:unknown"}]}))
    assert audit(path, manifest_path=manifest)["quality_gates"]["manifest_matches_index"] is False


def test_audit_check_fails_but_legacy_report_succeeds_for_missing_index(tmp_path):
    command = [sys.executable, "scripts/audit_corpus.py", "--index", str(tmp_path / "missing.sqlite3"),
               "--output", str(tmp_path / "audit.json")]
    normal = subprocess.run(command, capture_output=True, text=True)
    checked = subprocess.run(command + ["--check"], capture_output=True, text=True)
    assert normal.returncode == 0
    assert checked.returncode == 1
    assert json.loads((tmp_path / "audit.json").read_text())["passed"] is False


def test_manifest_checksum_and_record_fields_detect_stale_ledger(tmp_path):
    import hashlib
    path = tmp_path / "corpus.sqlite3"
    make_index(path, [{}])
    manifest = tmp_path / "manifest.json"
    payload = {"index_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "records": [
        {"canonical_source_id": "pmid:1", "content_status": "full_text", "identity_status": "verified_title",
         "evidence_level": "RCT", "topic": "高血压", "disposition": "retained"}]}
    manifest.write_text(json.dumps(payload))
    assert audit(path, manifest)["quality_gates"]["manifest_matches_index"] is True
    payload["records"][0]["evidence_level"] = "Other"
    manifest.write_text(json.dumps(payload))
    assert audit(path, manifest)["quality_gates"]["manifest_matches_index"] is False
    payload["records"][0]["evidence_level"] = "RCT"
    payload["index_sha256"] = "0" * 64
    manifest.write_text(json.dumps(payload))
    assert audit(path, manifest)["quality_gates"]["manifest_matches_index"] is False


@pytest.mark.parametrize("missing_field", [
    "topic", "evidence_level", "classification_basis", "classification_review_status", "source_url", "acquired_at",
    "authorization", "permitted_use", "file_sha256", "metadata_sha256", "parser_version", "anomaly_reasons", "index_version",
])
def test_required_ledger_fields_cannot_be_omitted(tmp_path, missing_field):
    path = tmp_path / "corpus.sqlite3"
    make_index(path, [{}])
    manifest = tmp_path / "manifest.json"
    payload = complete_manifest(path)
    del payload["records"][0][missing_field]
    manifest.write_text(json.dumps(payload))
    report = audit(path, manifest)
    assert report["quality_gates"].get("ledger_schema_complete") is False
    assert missing_field in str(report["pdf_index"]["ledger_schema_errors"])


def test_manifest_requires_source_provenance_even_when_record_fields_are_complete(tmp_path):
    path = tmp_path / "corpus.sqlite3"
    make_index(path, [{}])
    manifest = tmp_path / "manifest.json"
    payload = complete_manifest(path)
    payload.pop("source_checksums_before")
    manifest.write_text(json.dumps(payload))
    report = audit(path, manifest)
    assert report["quality_gates"].get("ledger_provenance_complete") is False
    assert report["pdf_index"]["verified_full_text"] == 0


def test_old_substring_identity_label_without_header_evidence_is_not_verified_fulltext(tmp_path):
    path = tmp_path / "corpus.sqlite3"
    make_index(path, [{}])
    manifest = tmp_path / "manifest.json"
    payload = complete_manifest(path)
    payload["records"][0].pop("pdf_identity_evidence")
    payload["records"][0]["identity_basis"] = "exact normalized title in first two PDF pages"
    manifest.write_text(json.dumps(payload))
    report = audit(path, manifest)
    assert report["pdf_index"]["verified_full_text"] == 0
    assert report["quality_gates"]["full_text_rate_at_least_90_percent"] is False
