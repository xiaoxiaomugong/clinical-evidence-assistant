#!/usr/bin/env python3
"""Report corpus quality; --check explicitly turns failed gates into exit 1."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
for import_path in (ROOT, ROOT / "src"):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from config import settings
from scripts.lint_knowledge_pages import lint

CORE_TOPICS = ("高血压", "血脂", "糖尿病", "脑卒中", "心脑血管")
LEDGER_STRING_FIELDS = (
    "canonical_source_id", "topic", "evidence_level", "classification_review_status", "source_url", "acquired_at",
    "authorization", "permitted_use", "file_sha256", "metadata_sha256", "parser_version", "content_status",
    "disposition", "index_version",
)


def _sha256(value) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _verified_header_record(item: dict) -> bool:
    evidence = item.get("pdf_identity_evidence")
    if item.get("identity_status") != "verified_title" or not isinstance(evidence, dict):
        return False
    box = evidence.get("bbox")
    if not isinstance(box, list) or len(box) != 4 or not all(type(value) in (int, float) for value in box):
        return False
    body, title, boundary = (evidence.get(key) for key in ("body_font_size", "minimum_title_font_size", "before_section_boundary_y"))
    if not all(type(value) in (int, float) for value in (body, title, boundary)):
        return False
    return (evidence.get("method") == "exact_complete_prominent_header_title" and evidence.get("page") == 1
            and 0 <= box[0] < box[2] and 0 <= box[1] < box[3] < boundary and title > body > 0)


def _ledger_errors(manifest: dict, records: list) -> tuple:
    """Enforce the plan §4.3 ledger independently of quantitative gates.

    Explicit unknown provenance is visible; an omitted/empty field is not a
    record of uncertainty. This validates the ledger, not redistribution rights.
    """
    provenance = []
    for field in ("schema_version", "corpus_version", "parser_version", "created_at", "snapshot_method"):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            provenance.append(field + ": missing or empty")
    if not _sha256(manifest.get("index_sha256")):
        provenance.append("index_sha256: missing or invalid")
    for field in ("source_checksums_before", "source_checksums_after"):
        values = manifest.get(field)
        if not isinstance(values, dict) or not values or not all(isinstance(key, str) and key and _sha256(value) for key, value in values.items()):
            provenance.append(field + ": missing or invalid")
    if manifest.get("source_checksums_before") != manifest.get("source_checksums_after") or manifest.get("source_unchanged") is not True:
        provenance.append("source_unchanged: provenance does not establish unchanged inputs")
    errors = {}
    for position, item in enumerate(records):
        problems = []
        for field in LEDGER_STRING_FIELDS:
            if not isinstance(item.get(field), str) or not item[field].strip():
                problems.append(field + ": missing or empty")
        for field in ("classification_basis", "anomaly_reasons"):
            if not isinstance(item.get(field), list) or not all(isinstance(value, str) and value.strip() for value in item[field]):
                problems.append(field + ": missing or invalid list")
        if item.get("classification_basis") == [] and item.get("classification_review_status") not in {"metadata_missing", "unknown"}:
            problems.append("classification_basis: no basis for the declared classification")
        for field in ("file_sha256", "metadata_sha256"):
            value = item.get(field)
            if not _sha256(value) and value != "unknown":
                problems.append(field + ": must be SHA-256 or explicit unknown")
        if item.get("content_status") == "full_text" and item.get("file_sha256") == "unknown":
            problems.append("file_sha256: verified full text cannot have unknown checksum")
        if item.get("source_url") != "unknown" and not re.match(r"https?://[^/\s]+", str(item.get("source_url", ""))):
            problems.append("source_url: must be HTTP(S) URL or explicit unknown")
        if item.get("index_version") != manifest.get("corpus_version"):
            problems.append("index_version: does not match corpus_version")
        if item.get("parser_version") != manifest.get("parser_version"):
            problems.append("parser_version: does not match manifest parser")
        if problems:
            errors[item.get("canonical_source_id") or "missing-id:%s" % position] = problems
    if not records:
        errors["manifest"] = ["records: missing or empty"]
    return errors, provenance


def _json_records(path: Path) -> list:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, list) else []


def _normalized(text: str) -> str:
    return " ".join((text or "").casefold().split())


def _distribution(rows: list) -> dict:
    return {"documents": len(rows), **{
        key: dict(sorted(Counter(row[key] or ("Other" if key == "evidence_level" else "missing") for row in rows).items()))
        for key in ("topic", "evidence_level", "extraction_status")
    }}


def audit(index_path: Path = settings.pdf_index_path, manifest_path: Optional[Path] = None) -> dict:
    index_path = Path(index_path)
    local_records = _json_records(settings.local_corpus_path)
    knowledge_pages = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(settings.knowledge_dir.glob("*.json"))]
    lint_errors = [issue for issue in lint(settings.knowledge_dir) if issue["level"] == "error"]
    gates = {name: False for name in (
        "at_least_500_documents", "unique_primary_ids", "full_text_rate_at_least_90_percent",
        "each_core_topic_at_least_20_documents", "other_evidence_level_below_50_percent",
        "sqlite_integrity", "no_orphan_chunks", "fts_matches_chunks", "manifest_matches_index",
        "anomalies_accounted_for", "ledger_schema_complete", "ledger_provenance_complete",
    )}
    gates["knowledge_pages_lint"] = not lint_errors
    report = {
        "schema_version": "2.0", "created_at": datetime.now(timezone.utc).isoformat(),
        "corpus_version": settings.corpus_version,
        "counting_policy": "usable requires an indexed non-title chunk (>=80 characters); full text additionally requires >=300 characters, valid PDF and manifest identity verification",
        "bundled": {
            "knowledge_pages": len(knowledge_pages),
            "knowledge_claims": sum(len(page.get("claims", [])) for page in knowledge_pages),
            "snapshot_documents": len(local_records),
            "snapshot_topics": dict(Counter(item.get("topic", "missing") for item in local_records)),
            "snapshot_evidence_levels": dict(Counter(item.get("evidence_level", "missing") for item in local_records)),
            "knowledge_lint_errors": lint_errors,
        },
        "pdf_index": {"available": index_path.exists()}, "quality_gates": gates, "warnings": [],
    }
    if not index_path.exists():
        report["warnings"].append("本地 PDF 索引不存在，仅审计知识页与摘要快照。")
        report["passed"] = False
        return report

    ledger = []
    manifest = {}
    if manifest_path is None:
        manifest_path = index_path.with_suffix(".manifest.json")
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        ledger = manifest.get("records", [])
    ledger_by_id = {item.get("canonical_source_id") or "missing-id:%s" % position: item for position, item in enumerate(ledger)}
    ledger_errors, provenance_errors = _ledger_errors(manifest, ledger)
    with sqlite3.connect(index_path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        integrity = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        rows = [dict(row) for row in connection.execute("SELECT * FROM documents ORDER BY id")]
        chunks = list(connection.execute("SELECT id, doc_id, text FROM chunks"))
        chunk_by_doc = {}
        for chunk in chunks:
            chunk_by_doc.setdefault(chunk["doc_id"], []).append(chunk["text"])
        fts_mismatches = connection.execute("""
            SELECT COUNT(*) FROM (
              SELECT chunk_id, doc_id, title, text FROM chunk_fts
              EXCEPT SELECT c.id, c.doc_id, d.title, c.text FROM chunks c JOIN documents d ON d.id = c.doc_id
            )
        """).fetchone()[0] + connection.execute("""
            SELECT COUNT(*) FROM (
              SELECT c.id, c.doc_id, d.title, c.text FROM chunks c JOIN documents d ON d.id = c.doc_id
              EXCEPT SELECT chunk_id, doc_id, title, text FROM chunk_fts
            )
        """).fetchone()[0]
        fts_count = connection.execute("SELECT COUNT(*) FROM chunk_fts").fetchone()[0]

    ids = {row["id"] for row in rows}
    orphan_chunks = sum(chunk["doc_id"] not in ids for chunk in chunks)
    usable, content_full, verified_full, abstracts, title_only, unavailable = [], [], [], [], [], []
    for row in rows:
        texts = chunk_by_doc.get(row["id"], [])
        substantive = [text for text in texts if len(text.strip()) >= 80 and _normalized(text) != _normalized(row["title"])]
        item = ledger_by_id.get(row["id"], {})
        if row["extraction_status"] == "title_only" or (texts and all(_normalized(text) == _normalized(row["title"]) for text in texts)):
            title_only.append(row)
        elif substantive and row["extraction_status"] == "full_text" and row["valid_pdf"] and sum(map(len, substantive)) >= 300:
            usable.append(row)
            content_full.append(row)
            if not provenance_errors and row["id"] not in ledger_errors and _verified_header_record(item) and item.get("content_status") == "full_text":
                verified_full.append(row)
        elif substantive and row["extraction_status"] == "abstract_fallback" and len(row["abstract"].strip()) >= 80 and _normalized(row["abstract"]) != _normalized(row["title"]):
            # A metadata abstract absent from the actual index cannot earn usability.
            joined = _normalized(" ".join(texts))
            if _normalized(row["abstract"]) in joined:
                usable.append(row)
                abstracts.append(row)
            else:
                unavailable.append(row)
        else:
            unavailable.append(row)

    all_dist, usable_dist = _distribution(rows), _distribution(usable)
    # Preserve legacy top-level distribution field names while explicitly labelling both populations.
    all_dist["topics"] = all_dist.pop("topic")
    all_dist["evidence_levels"] = all_dist.pop("evidence_level")
    usable_dist["topics"] = usable_dist.pop("topic")
    usable_dist["evidence_levels"] = usable_dist.pop("evidence_level")
    denominator = len(usable)
    other = usable_dist["evidence_levels"].get("Other", 0)
    min_topic = min(usable_dist["topics"].get(topic, 0) for topic in CORE_TOPICS)
    manifest_matches = bool(ledger) and len(ledger) == len(rows) and len(ledger_by_id) == len(rows) and set(ledger_by_id) == ids
    if manifest_matches:
        manifest_matches = all(ledger_by_id[row["id"]].get("content_status") == row["extraction_status"] for row in rows)
        for row in rows:
            item = ledger_by_id[row["id"]]
            for field in ("pmid", "title", "topic", "evidence_level"):
                if field in item and item[field] != row[field]:
                    manifest_matches = False
            if "chunks" in item and item["chunks"] != len(chunk_by_doc.get(row["id"], [])):
                manifest_matches = False
    checksum_matches = None
    if manifest.get("index_sha256"):
        digest = hashlib.sha256()
        with index_path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        checksum_matches = digest.hexdigest() == manifest["index_sha256"]
        manifest_matches = manifest_matches and checksum_matches
        if not checksum_matches:
            verified_full = []
    anomaly_rows = [row for row in rows if row["extraction_status"] != "full_text" or not row["valid_pdf"] or row["extraction_error"]]
    anomalies_accounted = bool(ledger) and all(ledger_by_id.get(row["id"], {}).get("disposition") for row in anomaly_rows)
    years = [row["year"] for row in rows if row["year"] is not None]
    report["pdf_index"] = {
        "available": True, "documents": len(rows), "unique_pmids": len({row["pmid"] for row in rows}),
        "unique_titles": len({_normalized(row["title"]) for row in rows}), "chunks": len(chunks),
        "full_text": len(content_full), "verified_full_text": len(verified_full), "abstract_fallback": len(abstracts),
        "title_only": len(title_only), "unusable": len(title_only) + len(unavailable),
        "unusable_ids": [row["id"] for row in title_only + unavailable],
        "invalid_pdf": sum(not row["valid_pdf"] for row in rows),
        "year_range": [min(years), max(years)] if years else [None, None],
        "topics": all_dist["topics"], "evidence_levels": all_dist["evidence_levels"],
        "extraction_status": all_dist["extraction_status"],
        "all_records": all_dist, "usable_records": usable_dist,
        "ratios": {"other": other / denominator if denominator else None,
                   "verified_full_text": len(verified_full) / denominator if denominator else None},
        "core_topic_gaps": {topic: max(0, 20 - usable_dist["topics"].get(topic, 0)) for topic in CORE_TOPICS},
        "integrity_check": integrity, "orphan_chunks": orphan_chunks, "fts_mismatches": fts_mismatches,
        "manifest_records": len(ledger), "manifest_missing_ids": sorted(ids - set(ledger_by_id)),
        "manifest_extra_ids": sorted(set(ledger_by_id) - ids),
        "manifest_index_checksum_matches": checksum_matches,
        "ledger_schema_errors": ledger_errors, "ledger_provenance_errors": provenance_errors,
    }
    gates.update({
        "at_least_500_documents": denominator >= 500,
        "unique_primary_ids": len(rows) == len({row["pmid"] for row in rows}) and all(str(row["pmid"]).isdigit() and row["id"] == "pmid:" + row["pmid"] for row in rows),
        "full_text_rate_at_least_90_percent": bool(denominator) and len(verified_full) / denominator >= 0.9,
        "each_core_topic_at_least_20_documents": min_topic >= 20,
        "other_evidence_level_below_50_percent": bool(denominator) and other / denominator < 0.5,
        "sqlite_integrity": integrity == ["ok"], "no_orphan_chunks": orphan_chunks == 0,
        "fts_matches_chunks": fts_mismatches == 0 and fts_count == len(chunks),
        "manifest_matches_index": manifest_matches, "anomalies_accounted_for": anomalies_accounted,
        "ledger_schema_complete": not ledger_errors, "ledger_provenance_complete": not provenance_errors,
    })
    report["warnings"] = [name for name, passed in gates.items() if not passed]
    report["passed"] = all(gates.values())
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=settings.pdf_index_path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "corpus_quality.json")
    parser.add_argument("--check", action="store_true", help="Exit 1 when any quality gate fails (report-only remains the default).")
    args = parser.parse_args()
    report = audit(args.index, args.manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if args.check and not report["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
