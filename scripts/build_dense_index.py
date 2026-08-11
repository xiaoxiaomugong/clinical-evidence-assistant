#!/usr/bin/env python3
"""Build an immutable dense index outside the application request path."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
for import_path in (ROOT, ROOT / "src"):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from config import settings
from evidence_assistant.index_registry import DenseIndexError, IndexRegistry
from evidence_assistant.knowledge_base import KnowledgeBase
from evidence_assistant.retrievers import LocalCorpus, PdfCorpus, SentenceTransformerEncoder


def collect_chunks(include_pdf: bool = True):
    chunks = []
    chunks.extend(KnowledgeBase(settings.knowledge_dir).all_chunks())
    chunks.extend(LocalCorpus(settings.local_corpus_path).chunks)
    if include_pdf:
        chunks.extend(PdfCorpus(settings.pdf_index_path).all_chunks())
    deduped = {}
    for chunk in chunks:
        current = deduped.get(chunk.id)
        if current is None or len(chunk.text) > len(current.text):
            deduped[chunk.id] = chunk
    return [deduped[chunk_id] for chunk_id in sorted(deduped)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=settings.embedding_model)
    parser.add_argument("--revision", default=settings.embedding_model_revision)
    parser.add_argument("--corpus-version", default=settings.corpus_version)
    parser.add_argument("--output", type=Path, default=settings.vector_index_path)
    parser.add_argument("--batch-size", type=int, default=settings.embedding_batch_size)
    parser.add_argument("--exclude-pdf", action="store_true")
    parser.add_argument(
        "--allow-download",
        action="store_true",
        help="Allow the model runtime to download a missing model. Disabled by default.",
    )
    args = parser.parse_args()
    if not args.model:
        parser.error("--model or EMBEDDING_MODEL is required")

    chunks = collect_chunks(include_pdf=not args.exclude_pdf)
    if not chunks:
        raise SystemExit("No chunks were found; refusing to build an empty dense index")
    texts = [f"{chunk.title} {chunk.topic} {chunk.text}" for chunk in chunks]
    encoder = SentenceTransformerEncoder(
        args.model,
        model_revision=args.revision,
        batch_size=args.batch_size,
        local_files_only=not args.allow_download,
    )
    try:
        embeddings = encoder.encode(texts)
        path = IndexRegistry(args.output).write(
            corpus_version=args.corpus_version,
            model_name=args.model,
            model_revision=args.revision,
            chunks=chunks,
            embeddings=embeddings,
        )
    except DenseIndexError as error:
        raise SystemExit(str(error)) from error
    print(json.dumps({
        "index_path": str(path),
        "corpus_version": args.corpus_version,
        "model": args.model,
        "revision": args.revision,
        "chunks": len(chunks),
        "sources": sorted({chunk.source for chunk in chunks}),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
