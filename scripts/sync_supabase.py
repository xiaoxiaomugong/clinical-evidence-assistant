#!/usr/bin/env python3
"""Push local evidence to Supabase or pull an offline JSON snapshot from it."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import settings
from evidence_assistant.retrievers.hybrid import document_to_chunks
from evidence_assistant.retrievers.supabase import (
    SupabaseDataAPI,
    cloud_row_to_document,
)
from evidence_assistant.schemas import Chunk, Document


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def checksum(value) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def identifiers(document_id: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    prefix, _, value = document_id.partition(":")
    if prefix == "pmid":
        return value, None, None
    if prefix == "doi":
        return None, value, None
    if prefix == "nct":
        return None, None, value.upper()
    return None, None, None


def normalized_timestamp(value: str) -> str:
    if value:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            return value
        except ValueError:
            pass
    return utc_now()


def document_row(
    document: Document,
    *,
    rights_basis: str,
    metadata: Optional[dict] = None,
) -> dict:
    pmid, doi, nct_id = identifiers(document.id)
    content = {
        "id": document.id,
        "source_id": document.source,
        "title": document.title,
        "abstract": document.abstract,
        "journal": document.journal,
        "published_year": document.year,
        "authors": document.authors,
        "study_type": document.study_type,
        "status": document.status,
        "evidence_level": document.evidence_level,
        "url": document.url,
        "topic": document.topic,
    }
    return {
        **content,
        "source_record_id": document.id.partition(":")[2] or document.id,
        "pmid": pmid,
        "doi": doi,
        "nct_id": nct_id,
        "publication_types": [],
        "retrieved_at": normalized_timestamp(document.retrieved_at),
        "content_hash": checksum(content),
        "rights_basis": rights_basis,
        "metadata": metadata or {},
        "is_active": True,
    }


def chunk_row(
    chunk: Chunk,
    *,
    ordinal: int,
    content_kind: str,
    page_number: Optional[int] = None,
) -> dict:
    return {
        "id": chunk.id,
        "document_id": chunk.doc_id,
        "content_kind": content_kind,
        "page_number": page_number,
        "ordinal": ordinal,
        "text": chunk.text,
        "content_hash": checksum(chunk.text),
        "metadata": {},
    }


def load_snapshot(path: Path) -> Tuple[List[dict], List[dict]]:
    records = json.loads(path.read_text(encoding="utf-8"))
    documents = [Document(**{**record, "retrieved_at": record.get("retrieved_at", "")}) for record in records]
    document_rows = [
        document_row(
            document,
            rights_basis="Curated metadata/abstract snapshot; upstream source terms apply",
        )
        for document in documents
    ]
    chunk_rows = []
    for document in documents:
        for ordinal, chunk in enumerate(document_to_chunks(document), start=1):
            chunk_rows.append(
                chunk_row(chunk, ordinal=ordinal, content_kind="abstract")
            )
    return document_rows, chunk_rows


def load_pdf_index(path: Path, include_full_text: bool) -> Tuple[List[dict], List[dict]]:
    if not path.exists():
        raise FileNotFoundError(f"PDF index not found: {path}")
    with sqlite3.connect(str(path)) as connection:
        connection.row_factory = sqlite3.Row
        documents = list(
            connection.execute(
                """
                select id, pmid, title, abstract, journal, year, authors, study_type,
                       evidence_level, url, topic, extraction_status, page_count,
                       valid_pdf, extraction_error
                from documents
                order by id
                """
            )
        )
        stored_chunks = list(
            connection.execute(
                "select id, doc_id, page_number, text from chunks order by doc_id, id"
            )
        ) if include_full_text else []

    document_rows = []
    abstract_by_document = {}
    for row in documents:
        abstract = row["abstract"] or ""
        document = Document(
            id=row["id"],
            source="pdf_collection",
            title=row["title"],
            abstract=abstract,
            journal=row["journal"],
            year=row["year"],
            authors=list(json.loads(row["authors"] or "[]")),
            study_type=row["study_type"],
            evidence_level=row["evidence_level"] or "Other",
            url=row["url"] or "",
            topic=row["topic"] or "",
        )
        rights = (
            "Operator-confirmed right to process the local PDF full text"
            if include_full_text
            else "PubMed metadata/abstract only; local PDF full text excluded"
        )
        document_rows.append(
            document_row(
                document,
                rights_basis=rights,
                metadata={
                    "extraction_status": row["extraction_status"],
                    "page_count": row["page_count"],
                    "valid_pdf": bool(row["valid_pdf"]),
                    "extraction_error": row["extraction_error"],
                },
            )
        )
        if abstract:
            abstract_by_document[row["id"]] = document

    chunk_rows = []
    if include_full_text:
        ordinals = {}
        for row in stored_chunks:
            ordinals[row["doc_id"]] = ordinals.get(row["doc_id"], 0) + 1
            chunk = Chunk(
                id=row["id"],
                doc_id=row["doc_id"],
                source="pdf_collection",
                title="",
                text=row["text"],
                evidence_level="Other",
            )
            chunk_rows.append(
                chunk_row(
                    chunk,
                    ordinal=ordinals[row["doc_id"]],
                    content_kind="full_text" if row["page_number"] else "abstract",
                    page_number=row["page_number"],
                )
            )
    else:
        for document in abstract_by_document.values():
            for ordinal, chunk in enumerate(document_to_chunks(document), start=1):
                chunk_rows.append(
                    chunk_row(chunk, ordinal=ordinal, content_kind="abstract")
                )
    return document_rows, chunk_rows


def upload(
    api: SupabaseDataAPI,
    source_id: str,
    documents: Iterable[dict],
    chunks: Iterable[dict],
    batch_size: int,
) -> None:
    document_rows = list(documents)
    chunk_rows = list(chunks)
    run_id = api.start_ingestion(
        source_id,
        {
            "uploader": "scripts/sync_supabase.py",
            "schema_version": "2",
            "expected_chunks": len(chunk_rows),
        },
        records_seen=len(document_rows),
    )
    try:
        api.stage_rows(
            "evidence_document_staging",
            run_id,
            document_rows,
            batch_size=batch_size,
        )
        api.stage_rows(
            "evidence_chunk_staging",
            run_id,
            chunk_rows,
            batch_size=batch_size,
        )
        published = api.publish_ingestion(run_id)
    except Exception as error:
        try:
            api.abort_ingestion(
                run_id,
                f"{type(error).__name__}: {str(error)[:400]}",
            )
        except Exception:
            # The original failure is more useful. Any rows left behind are in
            # backend-only staging tables and cannot become searchable.
            pass
        raise
    print(
        f"Published {published['documents']} documents and {published['chunks']} "
        f"chunks atomically ({source_id})"
    )


def write_snapshot(api: SupabaseDataAPI, output: Path) -> None:
    documents = [cloud_row_to_document(row) for row in api.fetch_active_documents()]
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps([asdict(document) for document in documents], ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    print(f"Saved {len(documents)} active documents to {output}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    push = subparsers.add_parser(
        "push", help="Atomically replace a Supabase evidence source"
    )
    push.add_argument("--source", choices=("snapshot", "pdf", "all"), default="snapshot")
    push.add_argument("--batch-size", type=int, default=200)
    push.add_argument("--dry-run", action="store_true")
    push.add_argument(
        "--include-pdf-full-text",
        action="store_true",
        help="Acknowledge that you have the right to upload the local PDF text",
    )

    pull = subparsers.add_parser("pull", help="Download active cloud documents as offline JSON")
    pull.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "raw" / "supabase_corpus.json",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "pull":
        key = settings.supabase_publishable_key or settings.supabase_secret_key
        if not settings.supabase_url or not key:
            raise SystemExit(
                "Set SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY (or SUPABASE_SECRET_KEY)."
            )
        write_snapshot(
            SupabaseDataAPI(settings.supabase_url, key, timeout=settings.supabase_timeout),
            args.output,
        )
        return

    datasets = []
    if args.source in {"snapshot", "all"}:
        datasets.append(("pubmed_snapshot", *load_snapshot(settings.local_corpus_path)))
    if args.source in {"pdf", "all"}:
        datasets.append(
            (
                "pdf_collection",
                *load_pdf_index(settings.pdf_index_path, args.include_pdf_full_text),
            )
        )
    if args.dry_run:
        for source_id, documents, chunks in datasets:
            print(f"Dry run: {source_id} -> {len(documents)} documents, {len(chunks)} chunks")
        return
    if not settings.supabase_url or not settings.supabase_secret_key:
        raise SystemExit("Set SUPABASE_URL and backend-only SUPABASE_SECRET_KEY before push.")
    api = SupabaseDataAPI(
        settings.supabase_url,
        settings.supabase_secret_key,
        timeout=settings.supabase_timeout,
    )
    for source_id, documents, chunks in datasets:
        upload(api, source_id, documents, chunks, args.batch_size)


if __name__ == "__main__":
    main()
