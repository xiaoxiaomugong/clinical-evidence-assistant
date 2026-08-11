from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, List, Optional, Sequence, Set, Tuple

from .schemas import Chunk, SourceCitation


class DenseIndexError(RuntimeError):
    """Raised when a dense index is unavailable, incompatible, or corrupt."""


def _numpy():
    try:
        import numpy as np
    except ImportError as error:  # pragma: no cover - depends on optional extra
        raise DenseIndexError(
            "Dense retrieval requires the optional 'retrieval' dependencies. "
            "Install with: pip install -e '.[retrieval]'"
        ) from error
    return np


def _safe_component(value: str) -> str:
    readable = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.") or "unnamed"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"{readable[:72]}-{digest}"


def _chunk_record(chunk: Chunk) -> dict:
    return asdict(chunk)


def _chunk_from_record(record: dict) -> Chunk:
    payload = dict(record)
    payload["citations"] = [SourceCitation(**item) for item in payload.get("citations", [])]
    return Chunk(**payload)


def _record_lines(chunks: Iterable[Chunk]) -> List[str]:
    return [
        json.dumps(_chunk_record(chunk), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for chunk in chunks
    ]


def _checksum(lines: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for line in lines:
        digest.update(line.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class DenseIndexMetadata:
    schema_version: str
    corpus_version: str
    model_name: str
    model_revision: str
    dimension: int
    normalized: bool
    item_count: int
    record_checksum: str
    embedding_checksum: str
    created_at: str


class StoredDenseIndex:
    """Read-only matrix and chunk records loaded from a versioned index."""

    def __init__(self, metadata: DenseIndexMetadata, chunks: List[Chunk], embeddings: Any):
        self.metadata = metadata
        self.chunks = chunks
        self.embeddings = embeddings

    def search(
        self,
        vector: Any,
        top_k: int,
        allowed_sources: Optional[Set[str]] = None,
    ) -> List[Tuple[Chunk, float]]:
        np = _numpy()
        if top_k <= 0:
            return []
        query = np.asarray(vector, dtype=np.float32).reshape(-1)
        if query.shape[0] != self.metadata.dimension:
            raise DenseIndexError(
                f"Query dimension {query.shape[0]} does not match index dimension "
                f"{self.metadata.dimension}"
            )
        norm = float(np.linalg.norm(query))
        if not norm or not bool(np.all(np.isfinite(query))):
            return []
        query = query / norm
        scores = self.embeddings @ query
        ordered = np.argsort(-scores)
        results: List[Tuple[Chunk, float]] = []
        for raw_index in ordered:
            index = int(raw_index)
            chunk = self.chunks[index]
            if allowed_sources and chunk.source not in allowed_sources:
                continue
            results.append((chunk, float(scores[index])))
            if len(results) >= top_k:
                break
        return results


class IndexRegistry:
    """Resolve and validate immutable dense indexes by corpus and model version."""

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)

    def resolve(self, corpus_version: str, model_name: str, model_revision: str) -> Path:
        return (
            self.base_dir
            / _safe_component(corpus_version)
            / _safe_component(model_name)
            / _safe_component(model_revision)
        )

    def load(
        self,
        corpus_version: str,
        model_name: str,
        model_revision: str,
    ) -> StoredDenseIndex:
        np = _numpy()
        path = self.resolve(corpus_version, model_name, model_revision)
        metadata_path = path / "metadata.json"
        records_path = path / "records.jsonl"
        embeddings_path = path / "embeddings.npy"
        missing = [item.name for item in (metadata_path, records_path, embeddings_path) if not item.exists()]
        if missing:
            raise DenseIndexError(f"Dense index is missing {', '.join(missing)} at {path}")

        try:
            metadata = DenseIndexMetadata(**json.loads(metadata_path.read_text(encoding="utf-8")))
            lines = [line for line in records_path.read_text(encoding="utf-8").splitlines() if line]
            chunks = [_chunk_from_record(json.loads(line)) for line in lines]
            embeddings = np.load(str(embeddings_path), mmap_mode="r", allow_pickle=False)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise DenseIndexError(f"Cannot read dense index at {path}: {type(error).__name__}") from error

        if metadata.schema_version != "1.0":
            raise DenseIndexError(f"Unsupported dense index schema: {metadata.schema_version}")
        if metadata.corpus_version != corpus_version:
            raise DenseIndexError("Dense index corpus version mismatch")
        if metadata.model_name != model_name or metadata.model_revision != model_revision:
            raise DenseIndexError("Dense index model version mismatch")
        if metadata.item_count != len(chunks) or embeddings.shape[0] != len(chunks):
            raise DenseIndexError("Dense index record count mismatch")
        if len(embeddings.shape) != 2 or embeddings.shape[1] != metadata.dimension:
            raise DenseIndexError("Dense index embedding dimension mismatch")
        if not metadata.normalized:
            raise DenseIndexError("Dense index must contain normalized embeddings")
        if _checksum(lines) != metadata.record_checksum:
            raise DenseIndexError("Dense index record checksum mismatch")
        if _file_checksum(embeddings_path) != metadata.embedding_checksum:
            raise DenseIndexError("Dense index embedding checksum mismatch")
        return StoredDenseIndex(metadata, chunks, embeddings)

    def write(
        self,
        corpus_version: str,
        model_name: str,
        model_revision: str,
        chunks: Sequence[Chunk],
        embeddings: Any,
    ) -> Path:
        np = _numpy()
        matrix = np.asarray(embeddings, dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape[0] != len(chunks) or not len(chunks):
            raise DenseIndexError("Embeddings must be a non-empty 2D matrix aligned with chunks")
        if not bool(np.all(np.isfinite(matrix))):
            raise DenseIndexError("Dense index contains a non-finite embedding")
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        if np.any(norms == 0):
            raise DenseIndexError("Dense index contains a zero embedding")
        matrix = matrix / norms

        target = self.resolve(corpus_version, model_name, model_revision)
        if target.exists():
            raise DenseIndexError(
                f"Refusing to overwrite immutable dense index at {target}; "
                "use a new corpus or model revision"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".dense-index-", dir=str(target.parent)))
        try:
            lines = _record_lines(chunks)
            embeddings_path = temporary / "embeddings.npy"
            np.save(str(embeddings_path), matrix, allow_pickle=False)
            metadata = DenseIndexMetadata(
                schema_version="1.0",
                corpus_version=corpus_version,
                model_name=model_name,
                model_revision=model_revision,
                dimension=int(matrix.shape[1]),
                normalized=True,
                item_count=len(chunks),
                record_checksum=_checksum(lines),
                embedding_checksum=_file_checksum(embeddings_path),
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            (temporary / "metadata.json").write_text(
                json.dumps(asdict(metadata), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            (temporary / "records.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
            os.replace(str(temporary), str(target))
        except Exception:
            if temporary.exists():
                shutil.rmtree(temporary)
            raise
        return target
