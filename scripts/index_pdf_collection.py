#!/usr/bin/env python3
"""Build a local SQLite FTS index from the 500-PDF PMID collection."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pymupdf
import requests


ROOT = Path(__file__).resolve().parents[1]
for import_path in (ROOT, ROOT / "src"):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from config import settings
from evidence_assistant.retrievers.common import publication_type_to_level
from evidence_assistant.retrievers.pubmed import _parse_pubmed


pymupdf.TOOLS.mupdf_display_errors(False)
pymupdf.TOOLS.mupdf_display_warnings(False)


TOPIC_KEYWORDS = {
    "高血压": ["hypertension", "blood pressure", "antihypertensive"],
    "糖尿病": ["diabetes", "glycemic", "glucose", "insulin", "sglt2", "glp-1"],
    "脑卒中": ["stroke", "cerebrovascular", "transient ischemic", "intracerebral"],
    "血脂": ["lipid", "lipoprotein", "cholesterol", "triglyceride", "statin", "dyslipidemia"],
    "心脑血管": ["cardiovascular", "coronary", "atherosclerosis", "myocardial", "heart failure"],
}


def clean_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def chunk_text(text: str, max_chars: int = 1800, overlap: int = 220) -> Iterable[str]:
    text = clean_text(text)
    if not text:
        return
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            boundary = max(text.rfind(". ", start + max_chars // 2, end), text.rfind("; ", start, end))
            if boundary > start:
                end = boundary + 1
        piece = text[start:end].strip()
        if len(piece) >= 80:
            yield piece
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)


def detect_topic(text: str) -> str:
    lowered = text.lower()
    scores = {
        topic: sum(lowered.count(keyword) for keyword in keywords)
        for topic, keywords in TOPIC_KEYWORDS.items()
    }
    topic, score = max(scores.items(), key=lambda item: item[1])
    return topic if score else "其他"


def load_manifest(collection_dir: Path) -> List[dict]:
    path = collection_dir / "selected_manifest.csv"
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 500 or len({row["pmid"] for row in rows}) != 500:
        raise ValueError(f"Expected 500 unique manifest rows, found {len(rows)}")
    return rows


def fetch_pubmed(pmids: List[str], cache_path: Path, force: bool = False) -> Dict[str, dict]:
    if cache_path.exists() and not force:
        with cache_path.open("r", encoding="utf-8") as handle:
            return {item["id"].split(":", 1)[-1]: item for item in json.load(handle)}
    documents = []
    for offset in range(0, len(pmids), 100):
        batch = pmids[offset : offset + 100]
        params = {
            "db": "pubmed",
            "id": ",".join(batch),
            "rettype": "abstract",
            "retmode": "xml",
            "tool": "clinical-evidence-assistant",
        }
        if settings.ncbi_email:
            params["email"] = settings.ncbi_email
        if settings.pubmed_api_key:
            params["api_key"] = settings.pubmed_api_key
        response = requests.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            params=params,
            timeout=45,
        )
        response.raise_for_status()
        documents.extend(_parse_pubmed(response.text))
        print(f"PubMed metadata: {min(offset + 100, len(pmids))}/{len(pmids)}", flush=True)
        time.sleep(settings.rate_limit_seconds)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with cache_path.open("w", encoding="utf-8") as handle:
        json.dump([asdict(document) for document in documents], handle, ensure_ascii=False, indent=2)
    return {document.id.split(":", 1)[-1]: asdict(document) for document in documents}


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA journal_mode = OFF;
        PRAGMA synchronous = OFF;
        CREATE TABLE documents (
            id TEXT PRIMARY KEY,
            pmid TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            abstract TEXT NOT NULL,
            journal TEXT,
            year INTEGER,
            authors TEXT NOT NULL,
            study_type TEXT,
            evidence_level TEXT NOT NULL,
            url TEXT NOT NULL,
            topic TEXT NOT NULL,
            pdf_path TEXT NOT NULL,
            valid_pdf INTEGER NOT NULL,
            page_count INTEGER NOT NULL,
            extraction_status TEXT NOT NULL,
            extraction_error TEXT
        );
        CREATE TABLE chunks (
            id TEXT PRIMARY KEY,
            doc_id TEXT NOT NULL,
            page_number INTEGER,
            text TEXT NOT NULL,
            FOREIGN KEY(doc_id) REFERENCES documents(id)
        );
        CREATE INDEX chunks_doc_id ON chunks(doc_id);
        CREATE VIRTUAL TABLE chunk_fts USING fts5(
            chunk_id UNINDEXED,
            doc_id UNINDEXED,
            title,
            text,
            tokenize = 'unicode61 remove_diacritics 2'
        );
        """
    )


def pdf_magic(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return b"%PDF-" in handle.read(1024)
    except OSError:
        return False


TextBlock = Tuple[float, float, float, float, str]


def _is_two_column(blocks: List[TextBlock], page_width: float) -> bool:
    """Detect a stable two-column body from positioned text blocks."""
    if page_width <= 0 or len(blocks) < 4:
        return False
    midpoint = page_width / 2
    left_chars = 0
    right_chars = 0
    for x0, _, x1, _, text in blocks:
        block_width = x1 - x0
        center = (x0 + x1) / 2
        if block_width > page_width * 0.62:
            continue
        if center < midpoint - page_width * 0.05 and x1 <= midpoint + page_width * 0.08:
            left_chars += len(text)
        elif center > midpoint + page_width * 0.05 and x0 >= midpoint - page_width * 0.08:
            right_chars += len(text)
    return left_chars >= 120 and right_chars >= 120


def _order_column_region(blocks: List[TextBlock], midpoint: float) -> List[TextBlock]:
    left = []
    right = []
    for block in blocks:
        center = (block[0] + block[2]) / 2
        (left if center < midpoint else right).append(block)
    position = lambda block: (round(block[1], 1), block[0])
    return sorted(left, key=position) + sorted(right, key=position)


def order_text_blocks(blocks: List[TextBlock], page_width: float) -> List[TextBlock]:
    """Return blocks in single- or multi-column reading order.

    Full-width titles, abstracts, figures, and tables split a page into vertical
    regions. Inside each two-column region, the left column is read completely
    before the right column.
    """
    position = lambda block: (round(block[1], 1), block[0])
    if not _is_two_column(blocks, page_width):
        return sorted(blocks, key=position)

    midpoint = page_width / 2
    gutter = page_width * 0.04
    spanning = []
    column_blocks = []
    for block in blocks:
        x0, _, x1, _, _ = block
        crosses_gutter = x0 < midpoint - gutter and x1 > midpoint + gutter
        if x1 - x0 >= page_width * 0.62 or crosses_gutter:
            spanning.append(block)
        else:
            column_blocks.append(block)

    ordered = []
    remaining = list(column_blocks)
    for anchor in sorted(spanning, key=position):
        before = [block for block in remaining if block[1] < anchor[1]]
        if before:
            ordered.extend(_order_column_region(before, midpoint))
            before_ids = {id(block) for block in before}
            remaining = [block for block in remaining if id(block) not in before_ids]
        ordered.append(anchor)
    ordered.extend(_order_column_region(remaining, midpoint))
    return ordered


def extract_page_text(page: pymupdf.Page) -> str:
    blocks: List[TextBlock] = []
    for block in page.get_text("blocks", sort=True):
        if len(block) >= 7 and block[6] != 0:
            continue
        text = clean_text(str(block[4] or ""))
        if text:
            blocks.append((float(block[0]), float(block[1]), float(block[2]), float(block[3]), text))
    ordered = order_text_blocks(blocks, float(page.rect.width))
    return "\n\n".join(block[4] for block in ordered)


def extract_pdf(path: Path) -> Tuple[int, List[Tuple[int, str]], Optional[str]]:
    try:
        with pymupdf.open(str(path)) as document:
            page_count = document.page_count
            pages = []
            for page_number, page in enumerate(document, start=1):
                text = extract_page_text(page)
                if text:
                    pages.append((page_number, text))
            return page_count, pages, None
    except Exception as error:
        return 0, [], f"{type(error).__name__}: {str(error)[:300]}"


def build_index(collection_dir: Path, output: Path, pubmed: Dict[str, dict]) -> dict:
    manifest = load_manifest(collection_dir)
    temporary = output.with_suffix(output.suffix + ".tmp")
    if temporary.exists():
        temporary.unlink()
    output.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(temporary))
    create_schema(connection)
    stats = {"documents": 0, "full_text": 0, "fallback": 0, "invalid_pdf": 0, "chunks": 0, "errors": 0}

    for index, row in enumerate(manifest, start=1):
        pmid = row["pmid"]
        path = collection_dir / row["dest_pdf"]
        metadata = pubmed.get(pmid, {})
        title = metadata.get("title") or row["title"]
        abstract = clean_text(metadata.get("abstract") or "")
        journal = metadata.get("journal") or f"NLM {row.get('nlm_unique_id', '')}".strip()
        year = metadata.get("year") or (int(row["pub_year"]) if row.get("pub_year", "").isdigit() else None)
        authors = metadata.get("authors") or []
        study_type = metadata.get("study_type") or "PDF full text"
        evidence_level = metadata.get("evidence_level") or "Other"
        valid = path.exists() and pdf_magic(path)
        page_count, pages, error = extract_pdf(path) if valid else (0, [], "not a valid PDF file")
        extracted_chars = sum(len(text) for _, text in pages)
        full_text = extracted_chars >= 300
        status = "full_text" if full_text else "abstract_fallback"
        if not valid:
            stats["invalid_pdf"] += 1
        if error and valid:
            stats["errors"] += 1
        if full_text:
            stats["full_text"] += 1
        else:
            stats["fallback"] += 1
        topic_basis = " ".join([title, abstract, " ".join(text for _, text in pages[:2])])
        topic = detect_topic(topic_basis)
        document_id = f"pmid:{pmid}"
        connection.execute(
            "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                document_id, pmid, title, abstract, journal, year,
                json.dumps(authors, ensure_ascii=False), study_type, evidence_level,
                f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", topic,
                str(path.resolve()), int(valid), page_count, status, error,
            ),
        )

        chunk_rows = []
        if full_text:
            for page_number, page_text in pages:
                for chunk_number, text in enumerate(chunk_text(page_text), start=1):
                    chunk_rows.append((
                        f"{document_id}:pdf:p{page_number}:c{chunk_number}",
                        document_id,
                        page_number,
                        text,
                    ))
        fallback_text = abstract or title
        if not chunk_rows and fallback_text:
            chunk_rows.append((f"{document_id}:abstract", document_id, None, fallback_text))
        connection.executemany("INSERT INTO chunks VALUES (?, ?, ?, ?)", chunk_rows)
        connection.executemany(
            "INSERT INTO chunk_fts(chunk_id, doc_id, title, text) VALUES (?, ?, ?, ?)",
            [(chunk_id, doc_id, title, text) for chunk_id, doc_id, _, text in chunk_rows],
        )
        stats["documents"] += 1
        stats["chunks"] += len(chunk_rows)
        if index % 25 == 0 or index == len(manifest):
            connection.commit()
            print(
                f"Indexed {index}/{len(manifest)} PDFs | full_text={stats['full_text']} "
                f"fallback={stats['fallback']} chunks={stats['chunks']}",
                flush=True,
            )

    connection.execute("INSERT INTO chunk_fts(chunk_fts) VALUES ('optimize')")
    connection.commit()
    connection.close()
    if output.exists():
        output.unlink()
    temporary.replace(output)
    stats["index_bytes"] = output.stat().st_size
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", type=Path, default=settings.pdf_collection_dir)
    parser.add_argument("--output", type=Path, default=settings.pdf_index_path)
    parser.add_argument("--skip-pubmed", action="store_true")
    parser.add_argument("--refresh-pubmed", action="store_true")
    args = parser.parse_args()
    manifest = load_manifest(args.collection)
    cache_path = settings.data_dir / "raw" / "pdf_collection_pubmed.json"
    pubmed = {}
    if not args.skip_pubmed:
        pubmed = fetch_pubmed(
            [row["pmid"] for row in manifest],
            cache_path,
            force=args.refresh_pubmed,
        )
    stats = build_index(args.collection, args.output, pubmed)
    report_path = args.output.with_suffix(".report.json")
    with report_path.open("w", encoding="utf-8") as handle:
        json.dump(
            {
                **stats,
                "collection_dir": str(args.collection.resolve()),
                "index_path": str(args.output.resolve()),
                "pubmed_metadata_records": len(pubmed),
                "manifest_records": len(manifest),
            },
            handle,
            ensure_ascii=False,
            indent=2,
        )
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
