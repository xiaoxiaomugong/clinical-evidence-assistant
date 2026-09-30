"""Small, local-only public API over the existing evidence pipeline.

Start with ``uvicorn evidence_assistant.web:create_app --factory``. This
entrypoint deliberately ignores development credentials and private PDF data.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import sysconfig
import tempfile
from contextlib import asynccontextmanager
from dataclasses import fields
from pathlib import Path
from threading import Lock
from typing import Dict, List, Literal, Optional
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Config normally loads .env at import time. Opt out before the first core import;
# never inspect dotenv contents or inherited credentials. Explicit settings below
# also protect this adapter when another entrypoint already imported the core.
_previous_ignore_env = os.environ.get("EVIDENCE_ASSISTANT_IGNORE_ENV")
os.environ["EVIDENCE_ASSISTANT_IGNORE_ENV"] = "1"
try:
    from .citation_check import sanitize_answer, verify
    from .config import Settings
    from .pipeline import EvidencePipeline
    from .query_rewrite import rewrite
    from .refusal import assess_safety
finally:
    if _previous_ignore_env is None:
        os.environ.pop("EVIDENCE_ASSISTANT_IGNORE_ENV", None)
    else:
        os.environ["EVIDENCE_ASSISTANT_IGNORE_ENV"] = _previous_ignore_env
    del _previous_ignore_env


DISCLAIMER = "仅供教学与研究，不构成诊断或治疗建议；请勿提交可识别患者身份的信息。"
VALIDATION_MESSAGE = "输入格式不正确；请检查问题、版本和 PICO 字段的长度与内容。"
ERROR_MESSAGE = "服务暂时无法完成处理，请稍后重试。"
REFUSAL_MESSAGES = {
    "PHI_BLOCKED": "输入中疑似包含可识别个人信息。请删除姓名、病历号、联系方式等信息后重新提问。",
    "PERSONALIZED_TREATMENT": "此问题涉及个人诊疗或用药决策，请咨询临床专业人员。可以改问一般性证据与适用范围。",
    "OUT_OF_SCOPE": "问题超出当前成人心脑血管病、血脂、高血压和糖尿病资料范围。",
    "UNVERIFIABLE_INTERVENTION": "当前无法核实该干预或疗法，请提供可核验的名称或公开文献标识。",
}
DEFAULT_REFUSAL = "现有本地资料不足以形成可靠回答。请缩小人群、干预或结局范围，并核对原始资料。"
PICO_LABELS = {"population": "人群", "intervention": "干预", "comparison": "对照", "outcome": "结局"}
MAX_BODY_BYTES = 65536


class PicoInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    population: Optional[str] = Field(default=None, max_length=500)
    intervention: Optional[str] = Field(default=None, max_length=500)
    comparison: Optional[str] = Field(default=None, max_length=500)
    outcome: Optional[str] = Field(default=None, max_length=500)


class QueryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    question: str = Field(min_length=1, max_length=2000)
    audience: Literal["public", "professional"]
    pico: Optional[PicoInput] = Field(default=None, description="问题与非空 PICO 字段合并后最多 4000 字符，包含中文字段标签、冒号和换行。")

    @field_validator("question")
    @classmethod
    def nonempty_question(cls, value):
        if not value.strip():
            raise ValueError("empty question")
        return value.strip()

    def combined_question(self):
        parts = [self.question]
        if self.pico:
            for name, label in PICO_LABELS.items():
                value = getattr(self.pico, name)
                if value and value.strip():
                    parts.append(f"{label}：{value.strip()}")
        return "\n".join(parts)

    @model_validator(mode="after")
    def bounded_combined_input(self):
        if len(self.combined_question()) > 4000:
            raise ValueError("combined input too long")
        return self


class PublicModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CorpusInfo(PublicModel):
    version: str
    updated_at: Optional[str]


class Claim(PublicModel):
    text: str
    citations: List[int]


class PublicAnswer(PublicModel):
    summary: str
    claims: List[Claim]
    limitations: List[str]
    disclaimer: str


class PublicSource(PublicModel):
    id: int
    title: str
    url: Optional[str]
    year: Optional[int]
    source_type: Literal["knowledge_page", "pubmed_snapshot"]
    study_type: Optional[str]
    evidence_level: Optional[str]
    publication_status: Optional[str]
    identifiers: Dict[str, str]
    excerpt: str = Field(max_length=800)


class QueryResponse(PublicModel):
    request_id: str
    audience: Literal["public", "professional"]
    status: Literal["answered", "refused", "error"]
    degraded: bool
    generation_method: Literal["extractive", "llm", "none"]
    message: Optional[str]
    answer: Optional[PublicAnswer]
    sources: List[PublicSource]
    corpus: CorpusInfo
    online_search: Literal[False]


class Topic(PublicModel):
    id: str
    title: str
    summary: str
    updated_at: Optional[str]
    review_status: str
    reviewer: Optional[str]
    version: str
    scope: List[str]


class TopicList(PublicModel):
    topics: List[Topic]
    corpus: CorpusInfo


class TopicReference(PublicModel):
    title: str
    url: Optional[str]
    identifier: Optional[str]


class TopicDetail(Topic):
    content: List[str]
    references: List[TopicReference]
    corpus: CorpusInfo


class PublicMessage(PublicModel):
    message: str


def _safe_url(value):
    if not isinstance(value, str) or not value or re.search(r"[\s\\\x00-\x1f\x7f]", value):
        return None
    try:
        url = urlsplit(value)
        if url.scheme.lower() not in {"https", "http"} or not url.hostname or url.username or url.password:
            return None
        if url.hostname.lower() in {"localhost", "localhost.localdomain"}:
            return None
        try:
            if not ipaddress.ip_address(url.hostname).is_global:
                return None
        except ValueError:
            pass
        url.port  # Reject malformed ports, too.
        return value
    except ValueError:
        return None


def _resource_root():
    source = Path(__file__).resolve().parents[2]
    if (source / "data" / "knowledge_pages").is_dir():
        return source
    return Path(sysconfig.get_path("data")) / "share" / "clinical-evidence-assistant"


def _web_settings(root, runtime):
    data = root / "data"
    values = dict(
        root_dir=root, data_dir=data, cache_dir=runtime / "cache",
        knowledge_dir=data / "knowledge_pages", local_corpus_path=data / "raw" / "local_corpus.json",
        pdf_collection_dir=runtime / "disabled-pdf", pdf_index_path=runtime / "disabled-pdf" / "absent.sqlite3",
        corpus_version="v3", retrieval_backend="legacy", candidate_pool_policy="source_preserving",
        top8_selection_policy="legacy", embedding_model="", embedding_model_revision="main",
        vector_index_path=runtime / "disabled-indexes", rerank_backend="deterministic", rerank_model="",
        rerank_model_revision="main", model_local_files_only=True, retrieve_k=40,
        lexical_retrieve_k=30, dense_retrieve_k=30, top_k=8, generation_top_k=5,
        embedding_batch_size=16, rerank_batch_size=16, minimum_independent_sources=3, rrf_k=60,
        pre_refusal_threshold=0.18, post_failure_threshold=0.5, request_timeout=12,
        rate_limit_seconds=0.35, api_max_attempts=3, live_cache_ttl_seconds=3600,
        enable_live_apis=False, filter_preprint=True, llm_api_key="", llm_base_url="", llm_model="",
        pubmed_api_key="", ncbi_email="", enable_supabase=False, supabase_url="",
        supabase_publishable_key="", supabase_secret_key="", supabase_timeout=15,
    )
    # A future config field must be deliberately addressed before web startup.
    if {field.name for field in fields(Settings)} != set(values):
        raise RuntimeError("Web settings require review")
    return Settings(**values)


class _DisabledPdfCorpus:
    size = 0

    def search(self, *args, **kwargs):
        return []


def _load_topics(root):
    data = root / "data"
    manifest = json.loads((data / "corpus_version.json").read_text(encoding="utf-8"))
    corpus = {"version": str(manifest["version"]), "updated_at": manifest.get("updated_at") or manifest.get("created_at")}
    topics = {}
    for path in sorted((data / "knowledge_pages").glob("*.json")):
        page = json.loads(path.read_text(encoding="utf-8"))
        claims = page.get("claims", [])
        scope = list(dict.fromkeys(claim["applicable"] for claim in claims if claim.get("applicable")))
        topic = {
            "id": page["id"], "title": page["title"], "summary": page.get("summary", ""),
            "updated_at": page.get("updated_at"), "review_status": page.get("review_status") or "未记录",
            "reviewer": page.get("reviewer") or None, "version": page.get("version") or corpus["version"], "scope": scope,
        }
        content, references, seen = [], [], set()
        for claim in claims:
            parts = [claim["text"]]
            if claim.get("applicable"):
                parts.append("适用人群：" + claim["applicable"])
            if claim.get("exceptions"):
                parts.append("例外：" + claim["exceptions"])
            content.append(" ".join(parts))
            for citation in claim.get("citations", []):
                identifier = next((f"{key.upper()}: {citation[key]}" for key in ("pmid", "doi", "nct_id") if citation.get(key)), None)
                reference = {"title": citation.get("source", "来源"), "url": _safe_url(citation.get("url")), "identifier": identifier}
                fingerprint = (reference["title"], reference["url"], identifier)
                if fingerprint not in seen:
                    seen.add(fingerprint)
                    references.append(reference)
        if page.get("limitations"):
            content.append("局限：" + page["limitations"])
        topics[topic["id"]] = {**topic, "content": content, "references": references}
    if not topics:
        raise ValueError("No public topics")
    return corpus, topics


def _envelope(request_id, audience, corpus, *, status, message=None, degraded=False, answer=None, sources=None, generation_method="none"):
    return dict(request_id=request_id, audience=audience, status=status, degraded=degraded,
                generation_method=generation_method, message=message, answer=answer,
                sources=sources or [], corpus=dict(corpus), online_search=False)


def _identifiers(entry):
    identifiers = {}
    for citation in entry.citations:
        for name in ("pmid", "doi", "nct_id"):
            value = getattr(citation, name, None)
            if value:
                identifiers[name] = str(value)
    for prefix, name, pattern in (("pmid:", "pmid", r"\d{5,9}"), ("nct:", "nct_id", r"NCT\d{8}"), ("doi:", "doi", r"10\.\d{4,9}/\S+")):
        if entry.doc_id.startswith(prefix):
            value = entry.doc_id[len(prefix):]
            if re.fullmatch(pattern, value):
                identifiers[name] = value
    return identifiers


def _project_result(result, request_id, audience, corpus):
    if result.used_live_api:
        # A server wiring mistake must never be mislabeled as an offline result.
        raise ValueError("Unexpected online execution")
    if result.answer.refused:
        return _envelope(request_id, audience, corpus, status="refused",
                         message=REFUSAL_MESSAGES.get(result.answer.refusal_code, DEFAULT_REFUSAL), degraded=bool(result.degraded))
    generation_ids = set(result.generation_entry_ids)
    entries = [entry for entry in result.entries
               if entry.source in {"knowledge_page", "pubmed_snapshot"} and entry.id in generation_ids and entry.citation_number > 0]
    numbers = [entry.citation_number for entry in entries]
    if len(numbers) != len(set(numbers)):
        raise ValueError("Ambiguous citations")
    # The pipeline's check indexes its pre-sanitization answer. Reverify the final
    # answer against only the actual generation package to avoid stale indexes.
    clean = sanitize_answer(result.answer, verify(result.answer, entries))
    if not clean.paragraphs:
        return _envelope(request_id, audience, corpus, status="refused", message=DEFAULT_REFUSAL, degraded=bool(result.degraded))
    claims = [{"text": paragraph.text, "citations": list(paragraph.citation_ids)} for paragraph in clean.paragraphs]
    cited = {number for claim in claims for number in claim["citations"]}
    sources = [{"id": entry.citation_number, "title": entry.title, "url": _safe_url(entry.url),
                "year": entry.year, "source_type": entry.source, "identifiers": _identifiers(entry),
                "study_type": entry.study_type, "evidence_level": entry.evidence_level or None,
                "publication_status": entry.status,
                "excerpt": entry.text[:800]} for entry in entries if entry.citation_number in cited]
    method = "llm" if clean.generator.startswith("llm") else "extractive"
    limitations = list(clean.limitations)
    limitations.append("本次仅检索内置知识页与精选文献快照，未进行在线更新；资料日期不代表当前最新证据。")
    answer = {"summary": "以下陈述来自本地资料，已通过引用与数字一致性检查。", "claims": claims,
              "limitations": limitations, "disclaimer": DISCLAIMER}
    return _envelope(request_id, audience, corpus, status="answered", degraded=bool(result.degraded),
                     message="已返回通过检查的本地资料回答。" if result.degraded else None,
                     answer=answer, sources=sources, generation_method=method)


class _RequestBoundary:
    """Bound even chunked bodies before parsing; never echo or log their content."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        sent = False

        async def safe_send(message):
            nonlocal sent
            if message["type"] == "http.response.start":
                sent = True
                headers = [(key, value) for key, value in message.get("headers", []) if key.lower() != b"cache-control"]
                message["headers"] = headers + [(b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff")]
            await send(message)

        try:
            chunks, size = [], 0
            for key, value in scope.get("headers", []):
                if key.lower() == b"content-length":
                    if int(value) > MAX_BODY_BYTES:
                        await JSONResponse({"message": "请求内容过大。"}, status_code=413)(scope, receive, safe_send)
                        return
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body = message.get("body", b"")
                size += len(body)
                if size > MAX_BODY_BYTES:
                    await JSONResponse({"message": "请求内容过大。"}, status_code=413)(scope, receive, safe_send)
                    return
                chunks.append(body)
                if not message.get("more_body", False):
                    break
            buffered = b"".join(chunks)

            async def replay():
                nonlocal buffered
                if buffered is not None:
                    body, buffered = buffered, None
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()

            await self.app(scope, replay, safe_send)
        except Exception:
            if not sent:
                await JSONResponse({"message": ERROR_MESSAGE}, status_code=503)(scope, receive, safe_send)


def create_app(pipeline=None):
    """Build a local API; pipeline injection is reserved for controlled tests."""
    runtime = tempfile.TemporaryDirectory(prefix="clinical-evidence-web-")
    corpus, topics = {"version": "unknown", "updated_at": None}, {}
    ready = False
    try:
        root = _resource_root()
        corpus, topics = _load_topics(root)
        if pipeline is None:
            pipeline = EvidencePipeline(_web_settings(root, Path(runtime.name)), recorder=None)
            pipeline.pdf_corpus = _DisabledPdfCorpus()
            if not pipeline.knowledge.size or not pipeline.local_corpus.size:
                raise ValueError("Public corpus unavailable")
        ready = True
    except Exception:
        # Health and requests expose a fixed unavailable state, never file paths.
        pipeline = None

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            runtime.cleanup()

    app = FastAPI(title="循证知问 · 本地 API", debug=False, docs_url=None, redoc_url=None, lifespan=lifespan)
    app.add_middleware(_RequestBoundary)
    lock = Lock()

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        return JSONResponse({"message": VALIDATION_MESSAGE}, status_code=422)

    @app.get("/health/live")
    def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    def readiness():
        return JSONResponse({"status": "ready" if ready else "unavailable"}, status_code=200 if ready else 503)

    @app.get("/api/v1/topics", response_model=TopicList)
    def list_topics():
        if not ready:
            return JSONResponse({"message": ERROR_MESSAGE}, status_code=503)
        summaries = [{key: value for key, value in topic.items() if key not in {"content", "references"}} for topic in topics.values()]
        return {"topics": summaries, "corpus": corpus}

    @app.get("/api/v1/topics/{topic_id}", response_model=TopicDetail)
    def topic_detail(topic_id: str):
        if not ready:
            return JSONResponse({"message": ERROR_MESSAGE}, status_code=503)
        if topic_id not in topics:
            return JSONResponse({"message": "未找到该主题。"}, status_code=404)
        return {**topics[topic_id], "corpus": corpus}

    @app.post("/api/v1/queries", response_model=QueryResponse,
              responses={413: {"model": PublicMessage}, 422: {"model": PublicMessage}, 503: {"model": QueryResponse}})
    def query(body: QueryInput):
        request_id = str(uuid4())
        if not ready or pipeline is None:
            return JSONResponse(_envelope(request_id, body.audience, corpus, status="error", message=ERROR_MESSAGE), status_code=503)
        try:
            question = body.combined_question()
            safety = assess_safety(rewrite(question))
            if safety.refused:
                return _envelope(request_id, body.audience, corpus, status="refused", message=REFUSAL_MESSAGES.get(safety.code, DEFAULT_REFUSAL))
            with lock:
                result = pipeline.run(question, mode="hybrid", enable_live_apis=False)
                # Validate and detach all public data while the mutable engine is
                # still locked; framework serialization sees only this DTO.
                return QueryResponse.model_validate(_project_result(result, request_id, body.audience, corpus)).model_dump()
        except Exception:
            return JSONResponse(_envelope(request_id, body.audience, corpus, status="error", message=ERROR_MESSAGE), status_code=503)

    return app
