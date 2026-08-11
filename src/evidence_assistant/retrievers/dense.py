from __future__ import annotations

from typing import Any, List, Optional, Sequence, Set

from ..index_registry import DenseIndexError, IndexRegistry, StoredDenseIndex
from ..interfaces import BackendStatus
from ..schemas import Chunk, QuerySpec


class SentenceTransformerEncoder:
    """Lazy optional sentence-transformers adapter used outside the default path."""

    def __init__(
        self,
        model_name: str,
        model_revision: str = "main",
        batch_size: int = 16,
        local_files_only: bool = True,
    ):
        self.model_name = model_name
        self.model_revision = model_revision
        self.batch_size = batch_size
        self.local_files_only = local_files_only
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:  # pragma: no cover - optional dependency
            raise DenseIndexError(
                "sentence-transformers is not installed; install the retrieval extra"
            ) from error
        try:
            self._model = SentenceTransformer(
                self.model_name,
                revision=self.model_revision,
                local_files_only=self.local_files_only,
            )
        except Exception as error:
            raise DenseIndexError(
                f"Cannot load embedding model {self.model_name}@{self.model_revision}: "
                f"{type(error).__name__}"
            ) from error
        return self._model

    def encode(self, texts: Sequence[str]):
        model = self._load()
        try:
            return model.encode(
                list(texts),
                batch_size=self.batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        except Exception as error:
            raise DenseIndexError(f"Embedding inference failed: {type(error).__name__}") from error


class DenseRetriever:
    """Search each query-language variant independently and fuse dense rankings."""

    def __init__(
        self,
        registry: IndexRegistry,
        corpus_version: str,
        model_name: str,
        model_revision: str = "main",
        batch_size: int = 16,
        local_files_only: bool = True,
        encoder: Optional[Any] = None,
        index: Optional[Any] = None,
        rrf_k: int = 60,
    ):
        self.registry = registry
        self.corpus_version = corpus_version
        self.model_name = model_name
        self.model_revision = model_revision
        self.rrf_k = rrf_k
        self.encoder = encoder or SentenceTransformerEncoder(
            model_name,
            model_revision=model_revision,
            batch_size=batch_size,
            local_files_only=local_files_only,
        )
        self._index: Optional[StoredDenseIndex] = index
        self.status = BackendStatus(requested="dense", actual="dense")

    def reset_status(self) -> None:
        self.status = BackendStatus(requested="dense", actual="dense")

    def _load_index(self):
        if self._index is None:
            self._index = self.registry.load(
                self.corpus_version,
                self.model_name,
                self.model_revision,
            )
        return self._index

    @staticmethod
    def _query_variants(spec: QuerySpec) -> List[str]:
        variants: List[str] = []
        for candidate in [spec.safe_query or spec.original, spec.original] + list(spec.api_queries):
            normalized = " ".join(candidate.split())
            if normalized and normalized not in variants:
                variants.append(normalized)
        if spec.local_terms:
            local_variant = " ".join(spec.local_terms[:24])
            if local_variant and local_variant not in variants:
                variants.append(local_variant)
        return variants[:6]

    def search(
        self,
        query_plan: QuerySpec,
        top_k: int,
        allowed_sources: Optional[Set[str]] = None,
    ) -> List[Chunk]:
        self.reset_status()
        if not self.model_name:
            self.status = BackendStatus(
                requested="dense",
                actual="legacy",
                degraded=True,
                reason="EMBEDDING_MODEL is not configured",
            )
            return []
        queries = self._query_variants(query_plan)
        if not queries or top_k <= 0:
            return []
        try:
            index = self._load_index()
            vectors = self.encoder.encode(queries)
            rankings = [
                index.search(vector, top_k=top_k, allowed_sources=allowed_sources)
                for vector in vectors
            ]
        except Exception as error:
            self.status = BackendStatus(
                requested="dense",
                actual="legacy",
                degraded=True,
                reason=str(error)[:300],
            )
            return []

        chunks = {}
        fused = {}
        best_similarity = {}
        for ranking in rankings:
            for rank, (chunk, similarity) in enumerate(ranking, start=1):
                chunks[chunk.id] = chunk
                fused[chunk.id] = fused.get(chunk.id, 0.0) + 1.0 / (self.rrf_k + rank)
                best_similarity[chunk.id] = max(best_similarity.get(chunk.id, -1.0), similarity)
        maximum = max(fused.values(), default=0.0)
        ordered = sorted(
            chunks,
            key=lambda chunk_id: (fused[chunk_id], best_similarity[chunk_id]),
            reverse=True,
        )
        results: List[Chunk] = []
        for chunk_id in ordered[:top_k]:
            chunk = Chunk(**{**chunks[chunk_id].__dict__})
            rrf_score = fused[chunk_id] / maximum if maximum else 0.0
            cosine_score = max(0.0, min(1.0, (best_similarity[chunk_id] + 1.0) / 2.0))
            chunk.retrieval_score = 0.65 * rrf_score + 0.35 * cosine_score
            results.append(chunk)
        return results
