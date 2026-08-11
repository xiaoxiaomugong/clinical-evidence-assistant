from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - zero-dependency runtime
    load_dotenv = None


ROOT_DIR = Path(__file__).resolve().parent
if load_dotenv:
    load_dotenv(ROOT_DIR / ".env")


def _as_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_path(value: str, default: Path) -> Path:
    if not value:
        return default
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT_DIR / path


@dataclass(frozen=True)
class Settings:
    root_dir: Path = ROOT_DIR
    data_dir: Path = ROOT_DIR / "data"
    cache_dir: Path = ROOT_DIR / "data" / "cache"
    knowledge_dir: Path = ROOT_DIR / "data" / "knowledge_pages"
    local_corpus_path: Path = ROOT_DIR / "data" / "raw" / "local_corpus.json"
    pdf_collection_dir: Path = ROOT_DIR / "500-collection"
    pdf_index_path: Path = ROOT_DIR / "data" / "raw" / "pdf_collection.sqlite3"
    corpus_version: str = "v3"
    retrieval_backend: str = os.getenv("RETRIEVAL_BACKEND", "legacy").strip().lower()
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "").strip()
    embedding_model_revision: str = os.getenv("EMBEDDING_MODEL_REVISION", "main").strip()
    vector_index_path: Path = _as_path(
        os.getenv("VECTOR_INDEX_PATH", ""), ROOT_DIR / "data" / "indexes"
    )
    rerank_backend: str = os.getenv("RERANK_BACKEND", "deterministic").strip().lower()
    rerank_model: str = os.getenv("RERANK_MODEL", "").strip()
    rerank_model_revision: str = os.getenv("RERANK_MODEL_REVISION", "main").strip()
    model_local_files_only: bool = _as_bool(os.getenv("MODEL_LOCAL_FILES_ONLY"), True)
    retrieve_k: int = int(os.getenv("RETRIEVE_K", "40"))
    lexical_retrieve_k: int = int(os.getenv("LEXICAL_RETRIEVE_K", "30"))
    dense_retrieve_k: int = int(os.getenv("DENSE_RETRIEVE_K", "30"))
    top_k: int = int(os.getenv("RERANK_K", os.getenv("TOP_K", "8")))
    generation_top_k: int = int(
        os.getenv("GENERATION_K", os.getenv("GENERATION_TOP_K", "5"))
    )
    embedding_batch_size: int = int(os.getenv("EMBEDDING_BATCH_SIZE", "16"))
    rerank_batch_size: int = int(os.getenv("RERANK_BATCH_SIZE", "16"))
    minimum_independent_sources: int = int(os.getenv("MINIMUM_INDEPENDENT_SOURCES", "3"))
    rrf_k: int = int(os.getenv("RRF_K", "60"))
    pre_refusal_threshold: float = float(os.getenv("PRE_REFUSAL_THRESHOLD", "0.18"))
    post_failure_threshold: float = float(os.getenv("POST_FAILURE_THRESHOLD", "0.5"))
    request_timeout: int = int(os.getenv("API_REQUEST_TIMEOUT", "12"))
    rate_limit_seconds: float = float(os.getenv("API_RATE_LIMIT_SECONDS", "0.35"))
    api_max_attempts: int = int(os.getenv("API_MAX_ATTEMPTS", "3"))
    live_cache_ttl_seconds: int = int(os.getenv("LIVE_CACHE_TTL_SECONDS", "3600"))
    enable_live_apis: bool = _as_bool(os.getenv("ENABLE_LIVE_APIS"), False)
    filter_preprint: bool = _as_bool(os.getenv("FILTER_PREPRINT"), True)
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    llm_model: str = os.getenv("LLM_MODEL", "gpt-4.1-mini")
    pubmed_api_key: str = os.getenv("PUBMED_API_KEY", "")
    ncbi_email: str = os.getenv("NCBI_EMAIL", "")

    def ensure_directories(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.pdf_index_path.parent.mkdir(parents=True, exist_ok=True)

    def normalized_retrieval_backend(self) -> str:
        return (
            self.retrieval_backend
            if self.retrieval_backend in {"legacy", "dense", "hybrid"}
            else "legacy"
        )

    def normalized_rerank_backend(self) -> str:
        return (
            self.rerank_backend
            if self.rerank_backend in {"deterministic", "cross_encoder"}
            else "deterministic"
        )


settings = Settings()
