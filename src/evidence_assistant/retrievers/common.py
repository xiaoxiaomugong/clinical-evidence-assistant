from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests

from ..schemas import Document


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def cache_path(cache_dir: Path, source: str, query: str, top_k: int, corpus_version: str) -> Path:
    digest = hashlib.sha256(f"{source}|{query}|{top_k}|{corpus_version}".encode("utf-8")).hexdigest()[:20]
    return Path(cache_dir) / f"{source}_{digest}.json"


def load_cache(path: Path, max_age_seconds: Optional[int] = None) -> Optional[List[Document]]:
    if not path.exists():
        return None
    if max_age_seconds is not None:
        age_seconds = max(0.0, time.time() - path.stat().st_mtime)
        if age_seconds > max_age_seconds:
            return None
    with path.open("r", encoding="utf-8") as handle:
        return [Document(**item) for item in json.load(handle)]


def save_cache(path: Path, documents: List[Document]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump([asdict(document) for document in documents], handle, ensure_ascii=False, indent=2)
    temporary.replace(path)


_RATE_LOCK = threading.Lock()
_NEXT_REQUEST_AT: Dict[str, float] = {}
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _reserve_request_slot(source: str, min_interval: float) -> None:
    with _RATE_LOCK:
        now = time.monotonic()
        request_at = max(now, _NEXT_REQUEST_AT.get(source, now))
        _NEXT_REQUEST_AT[source] = request_at + max(0.0, min_interval)
    delay = request_at - now
    if delay > 0:
        time.sleep(delay)


def get_with_retry(
    source: str,
    url: str,
    *,
    params: dict,
    timeout: int,
    min_interval: float,
    max_attempts: int,
) -> requests.Response:
    """Perform a rate-limited GET with bounded transient-error retries."""
    attempts = max(1, max_attempts)
    for attempt in range(attempts):
        _reserve_request_slot(source, min_interval)
        try:
            response = requests.get(
                url,
                params=params,
                headers={
                    "User-Agent": "clinical-evidence-assistant/0.1",
                    "Accept": "application/json, application/xml;q=0.9, text/xml;q=0.8",
                },
                timeout=timeout,
            )
        except (requests.ConnectionError, requests.Timeout):
            if attempt + 1 >= attempts:
                raise
            time.sleep(0.4 * (2 ** attempt))
            continue
        if response.status_code not in _RETRYABLE_STATUS or attempt + 1 >= attempts:
            return response
        retry_after = response.headers.get("Retry-After", "")
        try:
            delay = max(0.0, float(retry_after))
        except ValueError:
            delay = 0.4 * (2 ** attempt)
        time.sleep(delay)
    raise RuntimeError("unreachable")


def publication_type_classification(publication_types: List[str], is_preprint: bool = False) -> dict:
    """Map explicit publication labels, retaining uncertainty and the source basis.

    Generic journal/research-support labels never establish a study design.
    Review/meta-analysis overlap is normal; an original randomized trial and
    a synthesis/guideline label together require review instead of precedence.
    """
    normalized = {" ".join(item.lower().split()) for item in publication_types if item.strip()}
    basis = sorted(normalized)
    if is_preprint:
        level, status = "preprint", "metadata_mapped"
    else:
        synthesis = {"meta-analysis", "guideline", "practice guideline", "review", "systematic review",
                     "consensus development conference", "consensus development conference, nih", "consensus statement"}
        if "randomized controlled trial" in normalized and normalized & synthesis:
            level, status = "Other", "classification_conflict"
        elif "meta-analysis" in normalized:
            level, status = "Meta-analysis", "metadata_mapped"
        elif normalized & {"guideline", "practice guideline"}:
            level, status = "Guideline", "metadata_mapped"
        elif "randomized controlled trial" in normalized:
            level, status = "RCT", "metadata_mapped"
        elif normalized & {"consensus development conference", "consensus development conference, nih", "consensus statement"}:
            level, status = "Consensus", "metadata_mapped"
        elif normalized & {"review", "systematic review"}:
            level, status = "Review", "metadata_mapped"
        else:
            level, status = "Other", "unmapped_publication_type" if normalized else "metadata_missing"
    return {"evidence_level": level, "classification_basis": basis, "classification_review_status": status}


def publication_type_to_level(publication_types: List[str], is_preprint: bool = False) -> str:
    return publication_type_classification(publication_types, is_preprint)["evidence_level"]
