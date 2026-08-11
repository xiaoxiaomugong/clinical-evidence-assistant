from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Dict, List

from ..schemas import Chunk
from ..text_utils import bm25_scores, cosine_scores, ranked_indices, rrf_fuse


class PdfCorpus:
    """Search a disk-backed FTS index built from the 500-PDF collection."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def _scalar(self, sql: str) -> int:
        if not self.path.exists():
            return 0
        with sqlite3.connect(str(self.path)) as connection:
            return int(connection.execute(sql).fetchone()[0])

    @property
    def size(self) -> int:
        return self._scalar("SELECT COUNT(*) FROM documents")

    @property
    def full_text_count(self) -> int:
        return self._scalar("SELECT COUNT(*) FROM documents WHERE extraction_status = 'full_text'")

    @property
    def chunk_count(self) -> int:
        return self._scalar("SELECT COUNT(*) FROM chunks")

    def stats(self) -> Dict[str, int]:
        if not self.path.exists():
            return {"documents": 0, "full_text": 0, "fallback": 0, "invalid_pdf": 0, "chunks": 0}
        with sqlite3.connect(str(self.path)) as connection:
            documents = int(connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
            full_text = int(connection.execute(
                "SELECT COUNT(*) FROM documents WHERE extraction_status = 'full_text'"
            ).fetchone()[0])
            invalid_pdf = int(connection.execute(
                "SELECT COUNT(*) FROM documents WHERE valid_pdf = 0"
            ).fetchone()[0])
            chunks = int(connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
        return {
            "documents": documents,
            "full_text": full_text,
            "fallback": documents - full_text,
            "invalid_pdf": invalid_pdf,
            "chunks": chunks,
        }

    def all_chunks(self) -> List[Chunk]:
        """Return indexable records; this is used only by the offline dense-index builder."""
        if not self.path.exists():
            return []
        sql = """
            SELECT c.id AS chunk_id, c.doc_id, c.text, c.page_number,
                   d.title, d.journal, d.year, d.study_type, d.evidence_level,
                   d.url, d.topic
            FROM chunks AS c
            JOIN documents AS d ON d.id = c.doc_id
            ORDER BY c.id
        """
        with sqlite3.connect(str(self.path)) as connection:
            connection.row_factory = sqlite3.Row
            rows = list(connection.execute(sql))
        chunks = []
        for row in rows:
            page = row["page_number"]
            page_note = f" · PDF 第 {page} 页" if page else " · PubMed 摘要兜底"
            chunks.append(
                Chunk(
                    id=row["chunk_id"],
                    doc_id=row["doc_id"],
                    source="pdf_collection",
                    title=f"{row['title']}{page_note}",
                    text=row["text"],
                    evidence_level=row["evidence_level"] or "Other",
                    url=row["url"],
                    journal=row["journal"],
                    year=row["year"],
                    study_type=row["study_type"],
                    topic=row["topic"] or "",
                )
            )
        return chunks

    @staticmethod
    def _fts_query(terms: List[str]) -> str:
        joined = " ".join(terms)
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9]{1,}", joined.lower())
        stop = {
            "adult", "adults", "patient", "patients", "treatment", "clinical",
            "evidence", "guideline", "trial", "study", "management", "what", "how",
        }
        unique = []
        for token in tokens:
            if token not in stop and token not in unique:
                unique.append(token)
        return " OR ".join(f'"{token}"' for token in unique[:18])

    def search(self, terms: List[str], top_k: int = 14) -> List[Chunk]:
        if not self.path.exists():
            return []
        match = self._fts_query(terms)
        if not match:
            return []
        sql = """
            SELECT f.chunk_id, f.doc_id, f.text, c.page_number,
                   d.title, d.journal, d.year, d.authors, d.study_type,
                   d.evidence_level, d.url, d.topic, d.extraction_status,
                   bm25(chunk_fts, 0.0, 0.0, 1.4, 1.0) AS fts_rank
            FROM chunk_fts AS f
            JOIN chunks AS c ON c.id = f.chunk_id
            JOIN documents AS d ON d.id = f.doc_id
            WHERE chunk_fts MATCH ?
            ORDER BY fts_rank
            LIMIT 100
        """
        with sqlite3.connect(str(self.path)) as connection:
            connection.row_factory = sqlite3.Row
            rows = list(connection.execute(sql, (match,)))
        if not rows:
            return []

        query = " ".join(terms)
        searchable = [f"{row['title']} {row['topic']} {row['text']}" for row in rows]
        lexical = bm25_scores(query, searchable)
        semantic = cosine_scores(query, searchable)
        fused = rrf_fuse([
            ranked_indices(lexical, len(rows)),
            ranked_indices(semantic, len(rows)),
        ])
        ranked = sorted(
            range(len(rows)),
            key=lambda index: (fused.get(index, 0.0), lexical[index], semantic[index]),
            reverse=True,
        )
        ordered = []
        per_document: Dict[str, int] = {}
        for index in ranked:
            doc_id = rows[index]["doc_id"]
            if per_document.get(doc_id, 0) >= 2:
                continue
            ordered.append(index)
            per_document[doc_id] = per_document.get(doc_id, 0) + 1
            if len(ordered) >= top_k:
                break
        results: List[Chunk] = []
        for index in ordered:
            row = rows[index]
            page = row["page_number"]
            page_note = f" · PDF 第 {page} 页" if page else " · PubMed 摘要兜底"
            results.append(
                Chunk(
                    id=row["chunk_id"],
                    doc_id=row["doc_id"],
                    source="pdf_collection",
                    title=f"{row['title']}{page_note}",
                    text=row["text"],
                    evidence_level=row["evidence_level"] or "Other",
                    url=row["url"],
                    journal=row["journal"],
                    year=row["year"],
                    study_type=row["study_type"],
                    topic=row["topic"] or "",
                    retrieval_score=(
                        0.55 * fused.get(index, 0.0)
                        + 0.25 * lexical[index]
                        + 0.20 * semantic[index]
                    ),
                )
            )
        return results
