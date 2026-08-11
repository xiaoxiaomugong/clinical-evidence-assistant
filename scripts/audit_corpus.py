#!/usr/bin/env python3
"""Create a reproducible quality report for bundled and optional local corpora."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
for import_path in (ROOT, ROOT / "src"):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from config import settings


def _json_records(path: Path) -> list:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, list) else []


def _count_rows(connection: sqlite3.Connection, field: str) -> dict:
    allowed = {"topic", "evidence_level", "extraction_status"}
    if field not in allowed:
        raise ValueError(f"Unsupported audit field: {field}")
    rows = connection.execute(
        f"SELECT {field}, COUNT(*) FROM documents GROUP BY {field} ORDER BY COUNT(*) DESC"
    )
    return {str(label or "missing"): int(count) for label, count in rows}


def audit(index_path: Path = settings.pdf_index_path) -> dict:
    local_records = _json_records(settings.local_corpus_path)
    knowledge_pages = []
    for path in sorted(settings.knowledge_dir.glob("*.json")):
        with path.open("r", encoding="utf-8") as handle:
            knowledge_pages.append(json.load(handle))

    report = {
        "schema_version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "corpus_version": settings.corpus_version,
        "bundled": {
            "knowledge_pages": len(knowledge_pages),
            "knowledge_claims": sum(len(page.get("claims", [])) for page in knowledge_pages),
            "snapshot_documents": len(local_records),
            "snapshot_topics": dict(Counter(item.get("topic", "missing") for item in local_records)),
            "snapshot_evidence_levels": dict(
                Counter(item.get("evidence_level", "missing") for item in local_records)
            ),
        },
        "pdf_index": {"available": index_path.exists()},
        "quality_gates": {},
        "warnings": [],
    }

    if index_path.exists():
        with sqlite3.connect(str(index_path)) as connection:
            documents, unique_pmids, unique_titles, chunks, min_year, max_year = connection.execute(
                """
                SELECT COUNT(*), COUNT(DISTINCT pmid), COUNT(DISTINCT LOWER(TRIM(title))),
                       (SELECT COUNT(*) FROM chunks), MIN(year), MAX(year)
                FROM documents
                """
            ).fetchone()
            full_text = int(
                connection.execute(
                    "SELECT COUNT(*) FROM documents WHERE extraction_status = 'full_text'"
                ).fetchone()[0]
            )
            invalid_pdf = int(
                connection.execute("SELECT COUNT(*) FROM documents WHERE valid_pdf = 0").fetchone()[0]
            )
            report["pdf_index"] = {
                "available": True,
                "documents": int(documents),
                "unique_pmids": int(unique_pmids),
                "unique_titles": int(unique_titles),
                "chunks": int(chunks),
                "full_text": full_text,
                "abstract_fallback": int(documents) - full_text,
                "invalid_pdf": invalid_pdf,
                "year_range": [min_year, max_year],
                "topics": _count_rows(connection, "topic"),
                "evidence_levels": _count_rows(connection, "evidence_level"),
                "extraction_status": _count_rows(connection, "extraction_status"),
            }

        topics = report["pdf_index"]["topics"]
        levels = report["pdf_index"]["evidence_levels"]
        other_ratio = levels.get("Other", 0) / max(int(documents), 1)
        minimum_topic_count = min((topics.get(topic, 0) for topic in ("高血压", "血脂", "糖尿病", "脑卒中", "心脑血管")), default=0)
        report["quality_gates"] = {
            "at_least_500_documents": int(documents) >= 500,
            "unique_primary_ids": int(documents) == int(unique_pmids),
            "full_text_rate_at_least_90_percent": full_text / max(int(documents), 1) >= 0.9,
            "each_core_topic_at_least_20_documents": minimum_topic_count >= 20,
            "other_evidence_level_below_50_percent": other_ratio < 0.5,
        }
        if minimum_topic_count < 20:
            report["warnings"].append("核心主题分布不均，至少一个主题少于 20 篇。")
        if other_ratio >= 0.5:
            report["warnings"].append("超过一半文档的证据等级为 Other，需要补分类或人工抽查。")
        if invalid_pdf:
            report["warnings"].append(f"有 {invalid_pdf} 个文件未通过 PDF magic 检查并使用摘要兜底。")
    else:
        report["warnings"].append("本地 PDF 索引不存在，仅审计了随仓库分发的知识页与摘要快照。")

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=settings.pdf_index_path)
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "corpus_quality.json")
    args = parser.parse_args()
    report = audit(args.index)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
