from __future__ import annotations

import json
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlparse

import requests

from ..schemas import Chunk, Document


class SupabaseStoreError(RuntimeError):
    """Raised when the evidence Data API is unavailable or rejects a request."""


def _is_legacy_jwt(key: str) -> bool:
    return key.startswith("eyJ") and key.count(".") == 2


class SupabaseDataAPI:
    """Small PostgREST client for the project's evidence tables.

    The project already depends on ``requests``, so the cloud integration does
    not add a second HTTP/auth stack. New publishable and secret keys are sent
    only through ``apikey``; legacy JWT keys additionally require a Bearer
    header.
    """

    def __init__(
        self,
        url: str,
        key: str,
        *,
        timeout: int = 15,
        session: Optional[requests.Session] = None,
    ):
        normalized_url = url.strip().rstrip("/")
        parsed = urlparse(normalized_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("SUPABASE_URL must be an absolute http(s) URL")
        if not key.strip():
            raise ValueError("A Supabase publishable or secret key is required")
        self.base_url = f"{normalized_url}/rest/v1"
        self.key = key.strip()
        self.timeout = max(1, int(timeout))
        self.session = session or requests.Session()

    def _headers(self, *, prefer: str = "") -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "apikey": self.key,
        }
        if _is_legacy_jwt(self.key):
            headers["Authorization"] = f"Bearer {self.key}"
        if prefer:
            headers["Prefer"] = prefer
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        payload=None,
        prefer: str = "",
        extra_headers: Optional[Dict[str, str]] = None,
    ):
        headers = self._headers(prefer=prefer)
        if extra_headers:
            headers.update(extra_headers)
        try:
            response = self.session.request(
                method,
                f"{self.base_url}/{path.lstrip('/')}",
                params=params,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise SupabaseStoreError(
                f"Supabase Data API request failed: {type(error).__name__}"
            ) from error
        if response.status_code >= 400:
            detail = response.text.strip().replace("\n", " ")[:500]
            raise SupabaseStoreError(
                f"Supabase Data API returned HTTP {response.status_code}: {detail}"
            )
        if response.status_code == 204 or not response.content:
            return None, response
        try:
            return response.json(), response
        except (ValueError, json.JSONDecodeError) as error:
            raise SupabaseStoreError("Supabase Data API returned invalid JSON") from error

    def rpc(self, function_name: str, payload: dict):
        data, _ = self._request("POST", f"rpc/{function_name}", payload=payload)
        return data

    def count_active_documents(self) -> int:
        _, response = self._request(
            "GET",
            "evidence_documents",
            params={"select": "id", "is_active": "eq.true"},
            prefer="count=exact",
            extra_headers={"Range": "0-0"},
        )
        content_range = response.headers.get("Content-Range", "")
        try:
            return int(content_range.rsplit("/", 1)[-1])
        except (TypeError, ValueError):
            return 0

    def fetch_active_documents(self, page_size: int = 500) -> List[dict]:
        selected = (
            "id,source_id,title,abstract,journal,published_year,authors,"
            "study_type,status,evidence_level,url,topic,retrieved_at"
        )
        rows: List[dict] = []
        limit = min(max(int(page_size), 1), 1000)
        last_id = ""
        while True:
            params = {
                "select": selected,
                "is_active": "eq.true",
                "order": "id.asc",
                "limit": str(limit),
            }
            if last_id:
                params["id"] = f"gt.{last_id}"
            page, _ = self._request(
                "GET",
                "evidence_documents",
                params=params,
            )
            page = list(page or [])
            rows.extend(page)
            if len(page) < limit:
                break
            last_id = str(page[-1]["id"])
        return rows

    def upsert_rows(self, table: str, rows: Iterable[dict], batch_size: int = 200) -> int:
        records = list(rows)
        size = min(max(int(batch_size), 1), 500)
        for offset in range(0, len(records), size):
            self._request(
                "POST",
                table,
                params={"on_conflict": "id"},
                payload=records[offset : offset + size],
                prefer="resolution=merge-duplicates,return=minimal",
            )
        return len(records)

    def start_ingestion(self, source_id: str, metadata: Optional[dict] = None) -> str:
        rows, _ = self._request(
            "POST",
            "ingestion_runs",
            payload={"source_id": source_id, "metadata": metadata or {}},
            prefer="return=representation",
        )
        if not rows or not rows[0].get("id"):
            raise SupabaseStoreError("Supabase did not return an ingestion run id")
        return str(rows[0]["id"])

    def finish_ingestion(self, run_id: str, **fields) -> None:
        self._request(
            "PATCH",
            "ingestion_runs",
            params={"id": f"eq.{run_id}"},
            payload=fields,
            prefer="return=minimal",
        )


class SupabaseCorpus:
    """Read-only retriever backed by the secured full-text-search RPC."""

    def __init__(
        self,
        url: str,
        publishable_key: str,
        *,
        timeout: int = 15,
        session: Optional[requests.Session] = None,
    ):
        self.api = SupabaseDataAPI(
            url,
            publishable_key,
            timeout=timeout,
            session=session,
        )
        self._size: Optional[int] = None

    @property
    def size(self) -> int:
        if self._size is None:
            self._size = self.api.count_active_documents()
        return self._size

    def search(self, terms: List[str], top_k: int = 18) -> List[Chunk]:
        operands = []
        for term in terms[:24]:
            cleaned = term.strip().replace('"', " ")
            if not cleaned:
                continue
            operands.append(f'"{cleaned}"' if " " in cleaned else cleaned)
        query = " OR ".join(operands)
        if not query:
            return []
        rows = self.api.rpc(
            "search_evidence_chunks",
            {"search_query": query, "result_limit": min(max(top_k, 1), 100)},
        )
        chunks: List[Chunk] = []
        for row in rows or []:
            page = row.get("page_number")
            page_note = f" · PDF 第 {page} 页" if page else ""
            chunks.append(
                Chunk(
                    id=row["id"],
                    doc_id=row["doc_id"],
                    source=row["source"],
                    title=f"{row['title']}{page_note}",
                    text=row["text"],
                    evidence_level=row.get("evidence_level") or "Other",
                    url=row.get("url") or "",
                    journal=row.get("journal"),
                    year=row.get("year"),
                    study_type=row.get("study_type"),
                    status=row.get("status"),
                    topic=row.get("topic") or "",
                    retrieval_score=float(row.get("retrieval_score") or 0.0),
                )
            )
        return chunks


def cloud_row_to_document(row: dict) -> Document:
    return Document(
        id=row["id"],
        source=row["source_id"],
        title=row["title"],
        abstract=row.get("abstract") or "",
        journal=row.get("journal"),
        year=row.get("published_year"),
        authors=list(row.get("authors") or []),
        study_type=row.get("study_type"),
        status=row.get("status"),
        evidence_level=row.get("evidence_level") or "Other",
        url=row.get("url") or "",
        retrieved_at=row.get("retrieved_at") or "",
        topic=row.get("topic") or "",
    )
