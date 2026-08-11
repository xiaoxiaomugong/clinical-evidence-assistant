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
    top_k: int = int(os.getenv("TOP_K", "8"))
    rrf_k: int = 60
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


settings = Settings()
