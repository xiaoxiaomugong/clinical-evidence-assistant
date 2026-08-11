from __future__ import annotations

from typing import List

from config import Settings, settings
from ..schemas import Document, QuerySpec
from .common import cache_path, get_with_retry, load_cache, publication_type_to_level, save_cache, utc_now


def europepmc_search(spec: QuerySpec, top_k: int = 5, cfg: Settings = settings) -> List[Document]:
    query = spec.api_queries[0]
    path = cache_path(cfg.cache_dir, "europepmc", query, top_k, cfg.corpus_version)
    cached = load_cache(path, cfg.live_cache_ttl_seconds)
    if cached is not None:
        return cached
    params = {"query": query, "format": "json", "pageSize": top_k, "resultType": "core"}
    if cfg.ncbi_email:
        params["email"] = cfg.ncbi_email
    response = get_with_retry(
        "europepmc",
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        params=params,
        timeout=cfg.request_timeout,
        min_interval=cfg.rate_limit_seconds,
        max_attempts=cfg.api_max_attempts,
    )
    response.raise_for_status()
    documents: List[Document] = []
    for item in response.json().get("resultList", {}).get("result", []):
        source = item.get("source", "")
        is_preprint = source.upper() == "PPR" or item.get("pubType") == "preprint"
        if is_preprint and cfg.filter_preprint:
            continue
        pmid = item.get("pmid")
        record_id = f"pmid:{pmid}" if pmid else f"europepmc:{source}:{item.get('id', '')}"
        publication_types = item.get("pubTypeList", {}).get("pubType", [])
        documents.append(
            Document(
                id=record_id,
                source="europepmc",
                title=item.get("title", "Untitled"),
                abstract=item.get("abstractText") or item.get("title", ""),
                journal=item.get("journalTitle"),
                year=int(item["pubYear"]) if str(item.get("pubYear", "")).isdigit() else None,
                authors=[entry.get("fullName", "") for entry in item.get("authorList", {}).get("author", []) if entry.get("fullName")],
                study_type=", ".join(publication_types) or None,
                evidence_level=publication_type_to_level(publication_types, is_preprint=is_preprint),
                url=f"https://europepmc.org/article/{source}/{item.get('id', '')}",
                retrieved_at=utc_now(),
            )
        )
    save_cache(path, documents)
    return documents
