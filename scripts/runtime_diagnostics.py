#!/usr/bin/env python3
"""Read local runtime resources and write a new, privacy-safe administrator report.

Readiness here describes local resources, not provider connectivity or clinical quality.
No query, model loading, download, directory setup, or index construction is performed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

# Never serialize Settings or environment variables. Strings are fixed enums only.
ENUM_FIELDS = {
    "candidate_pool_policy": {"legacy", "source_preserving"},
    "top8_selection_policy": {"legacy", "document_diverse"},
    "retrieval_backend": {"legacy", "dense", "hybrid"},
    "rerank_backend": {"deterministic", "cross_encoder"},
}
BOOL_FIELDS = (
    "model_local_files_only", "enable_live_apis", "filter_preprint", "enable_supabase",
)
INTEGER_FIELDS = (
    "retrieve_k", "lexical_retrieve_k", "dense_retrieve_k", "top_k", "generation_top_k",
    "embedding_batch_size", "rerank_batch_size", "minimum_independent_sources", "rrf_k",
    "request_timeout", "api_max_attempts", "live_cache_ttl_seconds", "supabase_timeout",
)
FLOAT_FIELDS = (
    "pre_refusal_threshold", "post_failure_threshold", "rate_limit_seconds",
    "llm_request_timeout", "api_retry_sleep_cap_seconds",
)
PACKAGE_NAMES = (
    "clinical-evidence-assistant", "requests", "urllib3", "python-dotenv", "streamlit",
    "pytest", "pymupdf", "mcp", "numpy", "sentence-transformers",
)


def _configuration(cfg):
    result = {}
    invalid = False
    for field, allowed in ENUM_FIELDS.items():
        value = getattr(cfg, field, None)
        valid = isinstance(value, str) and value in allowed
        result[field] = value if valid else "invalid"
        invalid |= not valid
    for field in BOOL_FIELDS:
        value = getattr(cfg, field, None)
        valid = type(value) is bool
        result[field] = value if valid else None
        invalid |= not valid
    for field in INTEGER_FIELDS + FLOAT_FIELDS:
        if not hasattr(cfg, field):
            continue
        value = getattr(cfg, field)
        valid = type(value) in (int, float)
        if valid:
            try:
                valid = math.isfinite(value)
            except OverflowError:
                valid = False
        if valid:
            if field in INTEGER_FIELDS:
                valid = type(value) is int and value >= (0 if field == "live_cache_ttl_seconds" else 1)
            else:
                valid = value >= 0
                if field in {"pre_refusal_threshold", "post_failure_threshold"}:
                    valid &= value <= 1
        result[field] = value if valid else None
        invalid |= not valid
    return result, invalid


def _packages():
    versions = {}
    for name in PACKAGE_NAMES:
        try:
            value = metadata.version(name)
            versions[name] = value if re.fullmatch(r"[0-9][A-Za-z0-9.!+_-]{0,99}", value) else "unknown"
        except (metadata.PackageNotFoundError, ValueError, OSError):
            versions[name] = None
    return versions


def _build(root):
    result = {"commit": "unknown", "working_tree": "unknown"}
    try:
        commit = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True,
            text=True, check=True, timeout=5,
        ).stdout.strip()
        if re.fullmatch(r"[0-9a-fA-F]{40,64}", commit):
            result["commit"] = commit.lower()
            changed = subprocess.run(
                ["git", "--no-optional-locks", "-C", str(root), "status", "--porcelain"],
                capture_output=True, text=True, check=True, timeout=5,
            ).stdout
            result["working_tree"] = "modified" if changed else "clean"
    except (OSError, subprocess.SubprocessError):
        pass
    return result


def _read_json(path):
    content = path.read_bytes()
    return json.loads(content.decode("utf-8")), hashlib.sha256(content).hexdigest()


def _nonempty_strings(record, fields):
    return isinstance(record, dict) and all(
        isinstance(record.get(field), str) and record[field].strip() for field in fields
    )


def _knowledge(directory):
    result = {"status": "missing", "file_count": 0, "page_count": 0, "claim_count": 0, "sha256": None}
    try:
        paths = sorted(Path(directory).glob("*.json"))
        if not paths:
            return result
        result["file_count"] = len(paths)
        digest = hashlib.sha256()
        page_ids, claim_ids = set(), set()
        for path in paths:
            content = path.read_bytes()
            digest.update(path.name.encode("utf-8") + b"\0" + content + b"\0")
            page = json.loads(content.decode("utf-8"))
            if not _nonempty_strings(page, ("id", "title")) or page["id"] in page_ids:
                raise ValueError("invalid knowledge page")
            claims = page.get("claims")
            if not isinstance(claims, list) or not claims:
                raise ValueError("invalid knowledge claims")
            for claim in claims:
                if not _nonempty_strings(claim, ("text", "evidence_level")):
                    raise ValueError("invalid knowledge claim")
                if "id" in claim:
                    if not isinstance(claim["id"], str) or not claim["id"] or claim["id"] in claim_ids:
                        raise ValueError("invalid knowledge claim identity")
                    claim_ids.add(claim["id"])
            page_ids.add(page["id"])
            result["page_count"] += 1
            result["claim_count"] += len(claims)
        # Reuse the application's loader to check citation/schema compatibility.
        from evidence_assistant.knowledge_base import KnowledgeBase
        KnowledgeBase(Path(directory))
        result.update(status="valid", sha256=digest.hexdigest())
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        result["status"] = "invalid"
    return result


def _snapshot(path):
    result = {"status": "missing", "document_count": 0, "sha256": None}
    if not Path(path).is_file():
        return result
    try:
        content = Path(path).read_bytes()
        result["sha256"] = hashlib.sha256(content).hexdigest()
        records = json.loads(content.decode("utf-8"))
        if not isinstance(records, list):
            raise ValueError("invalid snapshot")
        from evidence_assistant.schemas import Document
        ids = set()
        for record in records:
            if not _nonempty_strings(record, ("id", "source", "title", "abstract")) or record["id"] in ids:
                raise ValueError("invalid snapshot document")
            Document(**record)
            ids.add(record["id"])
        result["document_count"] = len(records)
        result["status"] = "valid" if records else "empty"
    except (OSError, ValueError, TypeError, KeyError):
        result["status"] = "invalid"
    return result


def _manifest(cfg):
    result = {"status": "missing", "sha256": None, "matches_configuration": False}
    path = Path(cfg.data_dir) / "corpus_version.json"
    if not path.is_file():
        return result
    try:
        record, digest = _read_json(path)
        valid = _nonempty_strings(record, ("version",))
        result.update(status="valid" if valid else "invalid", sha256=digest,
                      matches_configuration=bool(valid and record["version"] == cfg.corpus_version))
    except (OSError, ValueError, TypeError):
        result["status"] = "invalid"
    return result


def _file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _pdf(path):
    path = Path(path)
    result = {"status": "absent_optional", "document_count": 0, "chunk_count": 0, "sha256": None}
    if not path.exists():
        return result
    # Immutable reads avoid SQLite sidecar writes, but cannot observe a live WAL.
    # Require an administrator's consistent snapshot rather than report stale data.
    if Path(str(path) + "-wal").exists():
        result["status"] = "unverified_wal"
        return result
    try:
        digest = _file_hash(path)
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True) as connection:
            connection.execute("PRAGMA query_only=ON")
            if connection.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise ValueError("invalid index")
            fts_schema = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='chunk_fts'"
            ).fetchone()
            if not fts_schema or not re.match(
                r"CREATE\s+VIRTUAL\s+TABLE\s+.*\s+USING\s+fts5\s*\(",
                fts_schema[0], flags=re.IGNORECASE | re.DOTALL,
            ):
                raise ValueError("invalid search engine")
            connection.execute(
                "SELECT COUNT(*) FROM chunk_fts WHERE chunk_fts MATCH ?", ('"runtime_diagnostic"',)
            ).fetchone()
            # Prepare the application's search shape without retrieving content.
            connection.execute("""
                SELECT f.chunk_id, f.doc_id, f.text, c.page_number,
                       d.title, d.journal, d.year, d.authors, d.study_type,
                       d.evidence_level, d.url, d.topic, d.extraction_status,
                       bm25(chunk_fts, 0.0, 0.0, 1.4, 1.0) AS fts_rank
                FROM chunk_fts f JOIN chunks c ON c.id=f.chunk_id
                JOIN documents d ON d.id=f.doc_id
                WHERE chunk_fts MATCH ? LIMIT 0
            """, ('"runtime_diagnostic"',))
            result["document_count"] = connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            result["chunk_count"] = connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            fts_count = connection.execute("SELECT COUNT(*) FROM chunk_fts").fetchone()[0]
            orphans = connection.execute(
                "SELECT COUNT(*) FROM chunks c LEFT JOIN documents d ON c.doc_id=d.id WHERE d.id IS NULL"
            ).fetchone()[0]
            fts_mismatches = connection.execute("""
                SELECT COUNT(*) FROM (
                    SELECT chunk_id, doc_id FROM chunk_fts
                    EXCEPT SELECT id, doc_id FROM chunks
                )
            """).fetchone()[0]
            missing_fts = connection.execute("""
                SELECT COUNT(*) FROM (
                    SELECT id, doc_id FROM chunks
                    EXCEPT SELECT chunk_id, doc_id FROM chunk_fts
                )
            """).fetchone()[0]
            duplicate_fts = connection.execute("""
                SELECT COUNT(*) FROM (
                    SELECT chunk_id FROM chunk_fts GROUP BY chunk_id HAVING COUNT(*) > 1
                )
            """).fetchone()[0]
            if orphans or fts_count != result["chunk_count"] or fts_mismatches or missing_fts or duplicate_fts:
                raise ValueError("invalid index relations")
        result["status"] = "valid" if result["document_count"] and result["chunk_count"] else "empty"
        result["sha256"] = digest
        if _file_hash(path) != digest:
            result["status"] = "changed_during_check"
    except (OSError, ValueError, sqlite3.Error):
        result["status"] = "invalid"
    return result


def _model_artifact(model):
    if not model:
        return "not_configured"
    try:
        return "present_unverified" if Path(model).is_dir() else "not_locally_verified"
    except (OSError, ValueError):
        return "not_locally_verified"


def _dense(cfg):
    result = {"status": "disabled", "item_count": 0, "inference_checked": False}
    if cfg.retrieval_backend not in {"dense", "hybrid"}:
        return result
    from evidence_assistant.index_registry import IndexRegistry, DenseIndexError
    registry = IndexRegistry(cfg.vector_index_path)
    target = registry.resolve(cfg.corpus_version, cfg.embedding_model, cfg.embedding_model_revision)
    result["model_artifact"] = _model_artifact(cfg.embedding_model)
    if not target.is_dir():
        result["status"] = "missing"
        return result
    try:
        index = registry.load(cfg.corpus_version, cfg.embedding_model, cfg.embedding_model_revision)
        result.update(status="valid", item_count=index.metadata.item_count,
                      record_sha256=index.metadata.record_checksum, embedding_sha256=index.metadata.embedding_checksum)
    except (DenseIndexError, OSError, ValueError, TypeError, KeyError, IndexError):
        result["status"] = "invalid"
    return result


def collect_diagnostics(cfg=None):
    """Return only allowlisted local facts; exceptions never enter the report."""
    packages = _packages()
    report = {
        "schema_version": "1.0", "checked_at": datetime.now(timezone.utc).isoformat(),
        "scope": "local_resources_only", "external_dependencies_checked": False,
        "status": "ready", "reason_codes": [], "build": {"commit": "unknown", "working_tree": "unknown"},
        "runtime": {"python_version": "%s.%s.%s" % sys.version_info[:3], "packages": packages},
        "configuration": {}, "corpus": {}, "resources": {},
    }
    if cfg is None:
        try:
            from evidence_assistant.config import settings
            cfg = settings
        except (OSError, ValueError, TypeError):
            report.update(status="not_ready", reason_codes=["configuration_invalid"])
            return report
    report["build"] = _build(cfg.root_dir)
    report["configuration"], invalid = _configuration(cfg)
    report["corpus"] = {
        "knowledge_pages": _knowledge(cfg.knowledge_dir), "snapshot": _snapshot(cfg.local_corpus_path),
        "version_manifest": _manifest(cfg),
    }
    report["resources"] = {
        "pdf_index": _pdf(cfg.pdf_index_path), "dense_index": _dense(cfg),
        "rerank_model": {"status": "disabled", "inference_checked": False},
    }
    if cfg.rerank_backend == "cross_encoder":
        report["resources"]["rerank_model"]["status"] = _model_artifact(cfg.rerank_model)
    reasons = report["reason_codes"]
    if invalid:
        reasons.append("configuration_invalid")
    if any(report["corpus"][name]["status"] != "valid" for name in ("knowledge_pages", "snapshot")):
        reasons.append("core_corpus_unavailable")
    if any(packages[name] is None for name in ("requests", "python-dotenv", "streamlit")):
        reasons.append("required_package_missing")
    not_ready = bool(reasons)
    if not report["corpus"]["version_manifest"]["matches_configuration"]:
        reasons.append("corpus_version_unverified")
    if report["resources"]["pdf_index"]["status"] not in {"valid", "absent_optional"}:
        reasons.append("pdf_index_unavailable")
    dense = report["resources"]["dense_index"]
    if dense["status"] not in {"disabled", "valid"}:
        reasons.append("dense_index_unavailable")
    # An artifact check cannot establish that a configured neural model loads or runs.
    if cfg.retrieval_backend in {"dense", "hybrid"} or cfg.rerank_backend == "cross_encoder":
        reasons.append("model_inference_unverified")
    report["status"] = "not_ready" if not_ready else "degraded" if reasons else "ready"
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New JSON file; parent directory must exist")
    args = parser.parse_args(argv)
    report = collect_diagnostics()
    try:
        # Exclusive creation handles races and refuses existing files and symlinks.
        with args.output.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
    except FileExistsError:
        parser.exit(2, "Report already exists; choose a new file.\n")
    except OSError:
        parser.exit(2, "Could not create report; check the output directory and permissions.\n")
    print("Runtime diagnostics: " + report["status"])
    return 1 if report["status"] == "not_ready" else 0


if __name__ == "__main__":
    raise SystemExit(main())
