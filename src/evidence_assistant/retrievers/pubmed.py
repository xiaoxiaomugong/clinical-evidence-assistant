from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import List

from config import Settings, settings
from ..schemas import Document, QuerySpec
from .common import cache_path, get_with_retry, load_cache, publication_type_to_level, save_cache, utc_now


BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def _text(node) -> str:
    return "".join(node.itertext()).strip() if node is not None else ""


def _parse_year(article) -> int:
    values = [
        article.findtext(".//JournalIssue/PubDate/Year", default=""),
        article.findtext(".//ArticleDate/Year", default=""),
        article.findtext(".//DateCompleted/Year", default=""),
        article.findtext(".//JournalIssue/PubDate/MedlineDate", default=""),
    ]
    for value in values:
        match = re.search(r"(?:19|20)\d{2}", value or "")
        if match:
            return int(match.group())
    return None


def _parse_pubmed(xml_text: str) -> List[Document]:
    root = ET.fromstring(xml_text)
    documents = []
    for record in root.findall(".//PubmedArticle"):
        citation = record.find("MedlineCitation")
        article = citation.find("Article") if citation is not None else None
        if article is None:
            continue
        pmid = citation.findtext("PMID", default="").strip()
        title = _text(article.find("ArticleTitle"))
        abstract = " ".join(_text(node) for node in article.findall("Abstract/AbstractText") if _text(node))
        publication_types = [_text(node) for node in article.findall("PublicationTypeList/PublicationType")]
        authors = []
        for author in article.findall("AuthorList/Author"):
            collective = author.findtext("CollectiveName", default="")
            name = collective or " ".join(filter(None, [author.findtext("ForeName"), author.findtext("LastName")]))
            if name:
                authors.append(name)
        documents.append(
            Document(
                id=f"pmid:{pmid}",
                source="pubmed",
                title=title,
                abstract=abstract or title,
                journal=article.findtext("Journal/Title"),
                year=_parse_year(record),
                authors=authors,
                study_type=", ".join(publication_types) or None,
                evidence_level=publication_type_to_level(publication_types),
                url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                retrieved_at=utc_now(),
            )
        )
    return documents


def pubmed_search(spec: QuerySpec, top_k: int = 5, cfg: Settings = settings) -> List[Document]:
    query = spec.api_queries[0]
    path = cache_path(cfg.cache_dir, "pubmed", query, top_k, cfg.corpus_version)
    cached = load_cache(path, cfg.live_cache_ttl_seconds)
    if cached is not None:
        return cached
    common = {"tool": "clinical-evidence-assistant"}
    if cfg.ncbi_email:
        common["email"] = cfg.ncbi_email
    if cfg.pubmed_api_key:
        common["api_key"] = cfg.pubmed_api_key
    min_interval = 0.11 if cfg.pubmed_api_key else max(cfg.rate_limit_seconds, 0.34)
    response = get_with_retry(
        "pubmed",
        f"{BASE_URL}/esearch.fcgi",
        params={"db": "pubmed", "term": query, "retmax": top_k, "retmode": "json", **common},
        timeout=cfg.request_timeout,
        min_interval=min_interval,
        max_attempts=cfg.api_max_attempts,
    )
    response.raise_for_status()
    pmids = response.json().get("esearchresult", {}).get("idlist", [])
    if not pmids:
        save_cache(path, [])
        return []
    fetched = get_with_retry(
        "pubmed",
        f"{BASE_URL}/efetch.fcgi",
        params={"db": "pubmed", "id": ",".join(pmids), "rettype": "abstract", "retmode": "xml", **common},
        timeout=cfg.request_timeout,
        min_interval=min_interval,
        max_attempts=cfg.api_max_attempts,
    )
    fetched.raise_for_status()
    documents = _parse_pubmed(fetched.text)
    save_cache(path, documents)
    return documents
