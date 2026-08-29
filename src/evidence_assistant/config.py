from __future__ import annotations

import os
import sysconfig
import tempfile
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - zero-dependency runtime
    load_dotenv = None


PACKAGE_DIR = Path(__file__).resolve().parent
SOURCE_ROOT = PACKAGE_DIR.parents[1]
INSTALLED_ROOT = (
    Path(sysconfig.get_path("data")) / "share" / "clinical-evidence-assistant"
)


def _discover_root() -> tuple[Path, bool]:
    configured = os.getenv("CLINICAL_EVIDENCE_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve(), False
    if (SOURCE_ROOT / "data" / "knowledge_pages").is_dir():
        return SOURCE_ROOT, True
    return INSTALLED_ROOT, False


ROOT_DIR, RUNNING_FROM_SOURCE = _discover_root()
if load_dotenv:
    env_file = os.getenv("EVIDENCE_ASSISTANT_ENV_FILE", "").strip()
    load_dotenv(Path(env_file).expanduser() if env_file else ROOT_DIR / ".env")


def _as_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_path(value: str, default: Path) -> Path:
    if not value:
        return default
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT_DIR / path


def _default_cache_dir() -> Path:
    if RUNNING_FROM_SOURCE:
        return ROOT_DIR / "data" / "cache"
    configured = os.getenv("XDG_CACHE_HOME", "").strip()
    if configured:
        return Path(configured).expanduser() / "clinical-evidence-assistant"
    return Path(tempfile.gettempdir()) / "clinical-evidence-assistant" / "cache"


DATA_DIR = _as_path(os.getenv("EVIDENCE_ASSISTANT_DATA_DIR", ""), ROOT_DIR / "data")


@dataclass(frozen=True)
class Settings:
    root_dir: Path = ROOT_DIR
    data_dir: Path = DATA_DIR
    cache_dir: Path = _as_path(
        os.getenv("EVIDENCE_ASSISTANT_CACHE_DIR", ""), _default_cache_dir()
    )
    knowledge_dir: Path = _as_path(
        os.getenv("KNOWLEDGE_DIR", ""), DATA_DIR / "knowledge_pages"
    )
    local_corpus_path: Path = _as_path(
        os.getenv("LOCAL_CORPUS_PATH", ""), DATA_DIR / "raw" / "local_corpus.json"
    )
    pdf_collection_dir: Path = _as_path(
        os.getenv("PDF_COLLECTION_DIR", ""), ROOT_DIR / "500-collection"
    )
    pdf_index_path: Path = _as_path(
        os.getenv("PDF_INDEX_PATH", ""), DATA_DIR / "raw" / "pdf_collection.sqlite3"
    )
    corpus_version: str = os.getenv("CORPUS_VERSION", "v3").strip()
    retrieval_backend: str = os.getenv("RETRIEVAL_BACKEND", "legacy").strip().lower()
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "").strip()
    embedding_model_revision: str = os.getenv("EMBEDDING_MODEL_REVISION", "main").strip()
    vector_index_path: Path = _as_path(
        os.getenv("VECTOR_INDEX_PATH", ""), DATA_DIR / "indexes"
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
    enable_supabase: bool = _as_bool(os.getenv("ENABLE_SUPABASE"), False)
    supabase_url: str = os.getenv("SUPABASE_URL", "").strip()
    supabase_publishable_key: str = os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()
    supabase_secret_key: str = os.getenv("SUPABASE_SECRET_KEY", "").strip()
    supabase_timeout: int = int(os.getenv("SUPABASE_TIMEOUT", "15"))

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
