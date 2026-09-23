#!/usr/bin/env python3
"""Build an isolated, non-overwritable corpus candidate from local files only.

The source SQLite file is opened read-only and backed up before modifications.
Exact normalized title matching in a prominent first-page article header is
identity evidence, not a medical or licensing review. Unconfirmed PDFs use only
an identity-matched cached abstract; they never silently earn full-text credit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for import_path in (ROOT, ROOT / "src"):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

import pymupdf
from config import settings
from evidence_assistant.retrievers.common import publication_type_classification
from scripts.audit_corpus import audit
from scripts.index_pdf_collection import chunk_text, clean_text, extract_pdf, load_manifest, pdf_magic

PARSER_VERSION = "p0-corpus-v2-header-title; PyMuPDF=" + pymupdf.VersionBind
INDEX_VERSION = "C1-vNext-local-candidate-v2"


def sha256_file(path: Path):
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _metadata_hash(metadata: dict) -> str:
    return hashlib.sha256(json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _title_key(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text).casefold()
    return "".join(char for char in normalized if char.isalnum())


def article_header_identity(path: Path, title: str) -> dict:
    """Accept a complete, prominent title in the first-page article header.

    A cited title in body text or References is not document identity. The
    rule deliberately leaves small-font titles and ambiguous layouts for
    manual review instead of treating arbitrary page substrings as evidence.
    """
    title_key = _title_key(title)
    if len(title_key) < 25:
        return {}
    with pymupdf.open(str(path)) as document:
        if not document.is_pdf or not document.page_count:
            return {}
        page = document[0]
        lines, size_weights = [], Counter()
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                spans = [span for span in line.get("spans", []) if span["text"].strip()]
                if not spans:
                    continue
                for span in spans:
                    size_weights[round(span["size"], 1)] += len(span["text"].strip())
                lines.append({"text": " ".join(span["text"] for span in spans), "bbox": line["bbox"], "spans": spans})
        if not size_weights:
            return {}
        # The character-weighted median resists a short oversized journal logo.
        half = sum(size_weights.values()) / 2
        cumulative, body_size = 0, 0.0
        for size, weight in sorted(size_weights.items()):
            cumulative += weight
            if cumulative >= half:
                body_size = size
                break
        lines.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
        section_top = min((line["bbox"][1] for line in lines if re.match(
            r"^\s*(abstract|background|introduction|references|bibliography)\b", line["text"], re.I)), default=page.rect.height)
        header_bottom = min(page.rect.height * 0.45, section_top)
        threshold = body_size + max(0.5, body_size * 0.08)
        prominent = []
        for line in lines:
            if line["bbox"][3] >= header_bottom:
                continue
            total = sum(len(span["text"].strip()) for span in line["spans"])
            large = sum(len(span["text"].strip()) for span in line["spans"] if span["size"] >= threshold)
            if large >= total * 0.9:
                prominent.append(line)
        for start in range(len(prominent)):
            group = []
            for line in prominent[start:start + 8]:
                if group and line["bbox"][1] - group[-1]["bbox"][3] > threshold * 1.5:
                    break
                group.append(line)
                candidate = _title_key(" ".join(item["text"] for item in group))
                if candidate == title_key:
                    return {"method": "exact_complete_prominent_header_title", "page": 1,
                            "bbox": [min(item["bbox"][0] for item in group), group[0]["bbox"][1],
                                     max(item["bbox"][2] for item in group), group[-1]["bbox"][3]],
                            "body_font_size": body_size, "minimum_title_font_size": threshold,
                            "before_section_boundary_y": section_top}
                if len(candidate) >= len(title_key):
                    break
    return {}


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare_candidate(source_index: Path, collection_dir: Path, metadata_cache: Path, output_dir: Path) -> dict:
    source_index, collection_dir, metadata_cache, output_dir = map(Path, (source_index, collection_dir, metadata_cache, output_dir))
    if output_dir.exists():
        raise FileExistsError("Candidate output already exists; choose a new directory: " + str(output_dir))
    manifest_rows = load_manifest(collection_dir)
    manifest_by_pmid = {row["pmid"]: row for row in manifest_rows}
    raw_metadata = json.loads(metadata_cache.read_text(encoding="utf-8"))
    metadata = {item["id"]: item for item in raw_metadata}
    if len(metadata) != len(raw_metadata):
        raise ValueError("Metadata cache IDs must be unique")
    inputs = [source_index, metadata_cache, collection_dir / "selected_manifest.csv"]
    before = {str(path.resolve()): sha256_file(path) for path in inputs}
    with sqlite3.connect(source_index.resolve().as_uri() + "?mode=ro", uri=True) as source:
        source.row_factory = sqlite3.Row
        integrity = [row[0] for row in source.execute("PRAGMA integrity_check")]
        if integrity != ["ok"]:
            raise ValueError("Source index failed integrity_check")
        original = [dict(row) for row in source.execute("SELECT * FROM documents ORDER BY pmid")]
        if {row["pmid"] for row in original} != set(manifest_by_pmid):
            raise ValueError("Source manifest IDs do not match index IDs")
        if any(row["id"] != "pmid:" + row["pmid"] for row in original):
            raise ValueError("Source index has inconsistent primary IDs")
        output_dir.mkdir(parents=True)
        output_index = output_dir / "corpus.sqlite3"
        with sqlite3.connect(str(output_index)) as connection:
            source.backup(connection)
    shutil.copyfile(metadata_cache, output_dir / "metadata-cache.json")
    shutil.copyfile(collection_dir / "selected_manifest.csv", output_dir / "selected_manifest.csv")
    records = []
    checked_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(str(output_index)) as connection:
        connection.execute("DELETE FROM chunks")
        connection.execute("DELETE FROM chunk_fts")
        for position, row in enumerate(original, 1):
            doc_id, pmid = row["id"], row["pmid"]
            manifest_row = manifest_by_pmid[pmid]
            path = (collection_dir / manifest_row["dest_pdf"]).resolve()
            if collection_dir.resolve() not in path.parents:
                raise ValueError("Manifest PDF path must remain inside collection")
            meta = metadata.get(doc_id, {})
            cached_title = meta.get("title", "")
            metadata_identity = bool(meta) and _title_key(cached_title) == _title_key(row["title"]) == _title_key(manifest_row["title"])
            title = row["title"]
            abstract = clean_text(meta.get("abstract") or "") if metadata_identity else ""
            types = meta.get("publication_types") or re.split(r",\s*", meta.get("study_type") or "")
            classification = publication_type_classification(types) if metadata_identity else publication_type_classification([])
            valid = pdf_magic(path)
            file_hash = sha256_file(path)
            page_count, pages, error = extract_pdf(path) if valid else (0, [], "missing_file" if not path.exists() else "invalid_pdf_magic")
            chars = sum(len(text) for _, text in pages)
            title_key = _title_key(title)
            identity_evidence = article_header_identity(path, title) if metadata_identity and valid and not error else {}
            verified_title = bool(identity_evidence)
            reasons = []
            if error:
                reasons.append(error)
            if valid and chars < 300:
                reasons.append("insufficient_extracted_text")
            if valid and not verified_title:
                reasons.append("pdf_title_identity_not_confirmed")
            if not metadata_identity:
                reasons.append("cached_metadata_title_or_id_not_confirmed")
            chunk_rows = []
            if valid and verified_title and chars >= 300:
                for page_number, text in pages:
                    for number, piece in enumerate(chunk_text(text), 1):
                        chunk_rows.append((f"{doc_id}:pdf:p{page_number}:c{number}", doc_id, page_number, piece))
            if chunk_rows:
                status, disposition, identity_status = "full_text", "retained_verified_full_text", "verified_title"
            elif len(abstract) >= 80 and _title_key(abstract) != title_key:
                status, disposition, identity_status = "abstract_fallback", "abstract_fallback", "verified_cached_metadata"
                chunk_rows = [(f"{doc_id}:abstract", doc_id, None, abstract)]
                if not reasons:
                    reasons.append("no_substantive_full_text_chunks")
            else:
                status, disposition, identity_status = "title_only", "excluded_from_usable_count", "unverified"
                chunk_rows = [(f"{doc_id}:title", doc_id, None, title)] if title else []
                reasons.append("no_substantive_identity_matched_abstract")
            connection.execute("""
                UPDATE documents SET abstract=?, study_type=?, evidence_level=?, pdf_path=?, valid_pdf=?,
                  page_count=?, extraction_status=?, extraction_error=? WHERE id=?
            """, (abstract, meta.get("study_type") or row["study_type"], classification["evidence_level"], str(path), int(valid),
                  page_count, status, "; ".join(reasons) or None, doc_id))
            connection.executemany("INSERT INTO chunks VALUES (?, ?, ?, ?)", chunk_rows)
            connection.executemany("INSERT INTO chunk_fts(chunk_id, doc_id, title, text) VALUES (?, ?, ?, ?)",
                                   [(chunk_id, document_id, title, text) for chunk_id, document_id, _, text in chunk_rows])
            records.append({
                "canonical_source_id": doc_id, "pmid": pmid, "title": title,
                "topic": row["topic"], "topic_basis": "frozen index primary topic, retained without speculative relabelling",
                **classification, "raw_publication_types": meta.get("study_type"),
                "previous_evidence_level": row["evidence_level"],
                "classification_change": classification["evidence_level"] != row["evidence_level"],
                "source_url": row["url"], "acquired_at": meta.get("retrieved_at") or "unknown",
                "authorization": "unknown", "permitted_use": "unknown; no redistribution grant inferred",
                "file_path": str(path), "file_sha256": file_hash or "unknown", "metadata_sha256": _metadata_hash(meta),
                "metadata_identity_status": "verified_title_and_id" if metadata_identity else "unverified",
                "metadata_cache": "metadata-cache.json", "parser_version": PARSER_VERSION,
                "checked_at": checked_at, "content_status": status, "identity_status": identity_status,
                "pdf_identity_status": "verified_title" if verified_title else "unverified",
                "identity_basis": "complete prominent title in first-page article header before body/References" if verified_title else "no positive PDF identity assertion",
                "pdf_identity_evidence": identity_evidence,
                "valid_pdf": valid, "page_count": page_count, "extracted_chars": chars,
                "historical_valid_pdf": bool(row["valid_pdf"]), "historical_status": row["extraction_status"],
                "anomaly_reasons": reasons, "disposition": disposition,
                "index_version": INDEX_VERSION, "chunks": len(chunk_rows),
                "manual_review_status": "not_reviewed",
            })
            if position % 50 == 0:
                print(f"Rechecked {position}/{len(original)} local files", flush=True)
        connection.execute("INSERT INTO chunk_fts(chunk_fts) VALUES ('optimize')")
        connection.commit()
    after = {str(path.resolve()): sha256_file(path) for path in inputs}
    if before != after:
        raise RuntimeError("Source changed during candidate preparation; candidate is not frozen")
    manifest_path = output_index.with_suffix(".manifest.json")
    _write_json(manifest_path, {
        "schema_version": "1.0", "corpus_version": INDEX_VERSION, "created_at": checked_at,
        "snapshot_method": "sqlite_backup_then_local_reparse", "parser_version": PARSER_VERSION,
        "source_checksums_before": before, "source_checksums_after": after, "source_unchanged": True,
        "index_sha256": sha256_file(output_index), "records": records,
        "limitations": ["Automated title matching is conservative and requires manual review when unconfirmed.",
                        "No new literature fetched; historical primary topics are retained.",
                        "Authorization is unknown and medical content support has not been independently reviewed."],
    })
    report = audit(output_index, manifest_path)
    _write_json(output_dir / "audit.json", report)
    anomalies = [item for item in records if not item["historical_valid_pdf"] or item["historical_status"] != "full_text" or item["anomaly_reasons"]]
    _write_json(output_dir / "anomaly-review.json", {"records": anomalies})
    summary = {
        "source_unchanged": True, "index": str(output_index.resolve()), "manifest": str(manifest_path.resolve()),
        "passed": report["passed"], "failed_gates": [key for key, value in report["quality_gates"].items() if not value],
        "classification_changes": sum(item["classification_change"] for item in records),
        "classification_review_status": dict(Counter(item["classification_review_status"] for item in records)),
        "historical_invalid_pdf_rechecked": sum(not item["historical_valid_pdf"] for item in records),
        "historical_fallback_rechecked": sum(item["historical_status"] != "full_text" for item in records),
        "current_pdf_identity": dict(Counter(item["pdf_identity_status"] for item in records)),
        "content_status": dict(Counter(item["content_status"] for item in records)),
        "artifacts_sha256": {path.name: sha256_file(path) for path in sorted(output_dir.iterdir()) if path.is_file()},
    }
    _write_json(output_dir / "summary.json", summary)
    # A rerun must use a new version directory; no old source or candidate is overwritten.
    for path in output_dir.iterdir():
        if path.is_file():
            path.chmod(0o444)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-index", type=Path, required=True)
    parser.add_argument("--collection", type=Path, default=settings.pdf_collection_dir)
    parser.add_argument("--metadata-cache", type=Path, default=ROOT / "data/raw/pdf_collection_pubmed.json")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    summary = prepare_candidate(args.source_index, args.collection, args.metadata_cache, args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if args.check and not summary["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
