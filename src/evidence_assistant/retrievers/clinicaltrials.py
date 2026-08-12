from __future__ import annotations

import re
from typing import List

from ..config import Settings, settings
from ..schemas import Document, QuerySpec
from .common import cache_path, get_with_retry, load_cache, save_cache, utc_now


def _clinicaltrials_query(spec: QuerySpec) -> str:
    terms = []
    for value in spec.local_terms[1:]:
        if not re.search(r"[A-Za-z]", value):
            continue
        cleaned = " ".join(value.replace('"', " ").replace("\\", " ").split())
        if cleaned and cleaned.lower() not in {item.lower() for item in terms}:
            terms.append(cleaned)
        if len(terms) >= 6:
            break
    if not terms:
        cleaned = " ".join(spec.original.replace('"', " ").replace("\\", " ").split())
        return f'"{cleaned}"'
    quoted = [f'"{term}"' for term in terms]
    if len(quoted) == 1:
        return quoted[0]
    return f"{quoted[0]} AND ({' OR '.join(quoted[1:])})"


def clinicaltrials_search(spec: QuerySpec, top_k: int = 5, cfg: Settings = settings) -> List[Document]:
    query = _clinicaltrials_query(spec)
    path = cache_path(cfg.cache_dir, "clinicaltrials", query, top_k, cfg.corpus_version)
    cached = load_cache(path, cfg.live_cache_ttl_seconds)
    if cached is not None:
        return cached
    response = get_with_retry(
        "clinicaltrials",
        "https://clinicaltrials.gov/api/v2/studies",
        params={"query.term": query, "pageSize": top_k, "format": "json"},
        timeout=cfg.request_timeout,
        min_interval=max(cfg.rate_limit_seconds, 0.5),
        max_attempts=cfg.api_max_attempts,
    )
    response.raise_for_status()
    documents: List[Document] = []
    for study in response.json().get("studies", []):
        protocol = study.get("protocolSection", {})
        identification = protocol.get("identificationModule", {})
        description = protocol.get("descriptionModule", {})
        design = protocol.get("designModule", {})
        status_module = protocol.get("statusModule", {})
        contacts = protocol.get("contactsLocationsModule", {})
        nct_id = identification.get("nctId", "")
        start_date = status_module.get("startDateStruct", {}).get("date", "")
        year = int(start_date[:4]) if len(start_date) >= 4 and start_date[:4].isdigit() else None
        organizations = contacts.get("overallOfficials", [])
        documents.append(
            Document(
                id=f"nct:{nct_id}",
                source="clinicaltrials",
                title=identification.get("briefTitle", nct_id),
                abstract=description.get("briefSummary") or identification.get("officialTitle", ""),
                journal="ClinicalTrials.gov",
                year=year,
                authors=[item.get("name", "") for item in organizations if item.get("name")],
                study_type=design.get("studyType"),
                status=status_module.get("overallStatus", "UNKNOWN"),
                evidence_level="ClinicalTrial",
                url=f"https://clinicaltrials.gov/study/{nct_id}",
                retrieved_at=utc_now(),
            )
        )
    save_cache(path, documents)
    return documents
