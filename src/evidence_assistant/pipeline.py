from __future__ import annotations

import time
from typing import List, Optional, Set, Tuple

import requests

from config import Settings, settings
from .candidate_pool import build
from .citation_check import sanitize_answer, verify
from .generate import generate
from .index_registry import IndexRegistry
from .interfaces import BackendStatus
from .knowledge_base import KnowledgeBase
from .query_rewrite import rewrite
from .refusal import assess_evidence, assess_post, assess_safety, refusal_answer
from .rerank import assign_citation_numbers, rerank as legacy_rerank, select_complementary
from .rerankers import CrossEncoderReranker, DeterministicReranker
from .retrievers import (
    DenseRetriever,
    HybridRetriever,
    LocalCorpus,
    PdfCorpus,
    PrecomputedRetriever,
    SupabaseCorpus,
    SupabaseStoreError,
    clinicaltrials_search,
    europepmc_search,
    pubmed_search,
)
from .schemas import Chunk, Document, EvidenceGateResult, PipelineResult, QuerySpec


MODE_LABELS = {
    "混合模式": "hybrid",
    "知识页优先": "knowledge",
    "RAG 优先": "rag",
    "hybrid": "hybrid",
    "knowledge": "knowledge",
    "rag": "rag",
}


class EvidencePipeline:
    def __init__(self, cfg: Settings = settings):
        self.settings = cfg
        self.settings.ensure_directories()
        self.knowledge = KnowledgeBase(cfg.knowledge_dir)
        self.local_corpus = LocalCorpus(cfg.local_corpus_path)
        self.pdf_corpus = PdfCorpus(cfg.pdf_index_path)
        self.supabase_corpus = None
        self.supabase_configuration_error = ""
        if cfg.enable_supabase:
            if not cfg.supabase_url or not cfg.supabase_publishable_key:
                self.supabase_configuration_error = (
                    "ENABLE_SUPABASE=true 但未配置 SUPABASE_URL/"
                    "SUPABASE_PUBLISHABLE_KEY"
                )
            else:
                try:
                    self.supabase_corpus = SupabaseCorpus(
                        cfg.supabase_url,
                        cfg.supabase_publishable_key,
                        timeout=cfg.supabase_timeout,
                    )
                except ValueError as error:
                    self.supabase_configuration_error = str(error)
        self.dense_retriever = DenseRetriever(
            registry=IndexRegistry(cfg.vector_index_path),
            corpus_version=cfg.corpus_version,
            model_name=cfg.embedding_model,
            model_revision=cfg.embedding_model_revision,
            batch_size=cfg.embedding_batch_size,
            local_files_only=cfg.model_local_files_only,
            rrf_k=cfg.rrf_k,
        )
        if cfg.normalized_rerank_backend() == "cross_encoder":
            self.reranker = CrossEncoderReranker(
                model_name=cfg.rerank_model,
                model_revision=cfg.rerank_model_revision,
                batch_size=cfg.rerank_batch_size,
                local_files_only=cfg.model_local_files_only,
            )
        else:
            self.reranker = DeterministicReranker()

    @staticmethod
    def _allowed_dense_sources(mode: str) -> Set[str]:
        if mode == "knowledge":
            return {"knowledge_page"}
        if mode == "rag":
            return {"pubmed_snapshot", "pdf_collection"}
        return {"knowledge_page", "pubmed_snapshot", "pdf_collection"}

    def _select_static_candidates(
        self,
        spec: QuerySpec,
        mode: str,
        knowledge_chunks: List[Chunk],
        local_chunks: List[Chunk],
        pdf_chunks: List[Chunk],
        cloud_chunks: List[Chunk],
        trace: List[str],
    ) -> Tuple[List[Chunk], BackendStatus]:
        requested = self.settings.retrieval_backend
        backend = self.settings.normalized_retrieval_backend()
        legacy_chunks = knowledge_chunks + local_chunks + pdf_chunks + cloud_chunks
        if requested not in {"legacy", "dense", "hybrid"}:
            reason = f"不支持的 RETRIEVAL_BACKEND={requested}"
            trace.append(f"检索后端配置无效，已降级为 legacy：{reason}")
            return legacy_chunks, BackendStatus(
                requested=requested,
                actual="legacy",
                degraded=True,
                reason=reason,
            )
        if backend == "legacy":
            return legacy_chunks, BackendStatus(requested="legacy", actual="legacy")

        dense_chunks = self.dense_retriever.search(
            spec,
            top_k=self.settings.dense_retrieve_k,
            allowed_sources=self._allowed_dense_sources(mode),
        )
        if self.dense_retriever.status.degraded:
            status = BackendStatus(
                requested=backend,
                actual="legacy",
                degraded=True,
                reason=self.dense_retriever.status.reason,
            )
            trace.append(f"{backend} 检索不可用，已降级为 legacy：{status.reason}")
            return legacy_chunks, status
        trace.append(f"稠密索引召回 {len(dense_chunks)} 个 chunk")
        if backend == "dense":
            # Supabase is queried independently of the local dense index. Keep
            # its lexical candidates in the same downstream rerank pool while
            # preserving dense candidates when both stores contain a chunk.
            merged = list(dense_chunks[: self.settings.retrieve_k])
            seen = {chunk.id for chunk in merged}
            for chunk in cloud_chunks:
                if chunk.id in seen:
                    continue
                merged.append(chunk)
                seen.add(chunk.id)
            if cloud_chunks:
                trace.append(
                    f"稠密/Supabase 合并后送入统一重排 {len(merged)} 个静态候选"
                )
            return merged, BackendStatus(
                requested="dense", actual="dense"
            )

        lexical_chunks = sorted(
            legacy_chunks,
            key=lambda chunk: chunk.retrieval_score,
            reverse=True,
        )[: self.settings.lexical_retrieve_k]
        retrievers = [
            PrecomputedRetriever(lexical_chunks),
            PrecomputedRetriever(dense_chunks, backend_name="dense"),
        ]
        hybrid = HybridRetriever(retrievers, rrf_k=self.settings.rrf_k)
        chunks = hybrid.search(spec, top_k=self.settings.retrieve_k)
        trace.append(f"词法/稠密 RRF 融合后保留 {len(chunks)} 个静态候选")
        return chunks, hybrid.status

    def _live_documents(self, spec, trace: List[str]) -> List[Document]:
        documents: List[Document] = []
        retrievers = [
            ("PubMed", pubmed_search),
            ("Europe PMC", europepmc_search),
            ("ClinicalTrials.gov", clinicaltrials_search),
        ]
        for label, retriever in retrievers:
            try:
                found = retriever(spec, top_k=4, cfg=self.settings)
                documents.extend(found)
                trace.append(f"{label} 返回 {len(found)} 条")
            except (requests.RequestException, ValueError, KeyError) as error:
                trace.append(f"{label} 不可用，已降级：{type(error).__name__}")
        return documents

    def run(
        self,
        question: str,
        mode: str = "hybrid",
        enable_live_apis: Optional[bool] = None,
        retrieval_profile: str = "normal",
    ) -> PipelineResult:
        started = time.perf_counter()
        canonical_mode = MODE_LABELS.get(mode, "hybrid")
        live_enabled = self.settings.enable_live_apis if enable_live_apis is None else enable_live_apis
        trace = ["查询改写：规则词典 + 中英文同义扩展"]
        spec = rewrite(question)
        trace.append(f"识别领域：{'、'.join(spec.domains) if spec.domains else '未命中'}")
        if spec.expected_evidence_types:
            trace.append(f"预期证据类型：{'、'.join(spec.expected_evidence_types)}")

        safety_gate = assess_safety(spec)
        if safety_gate.refused:
            trace.append(f"触发前置拒答/安全门控：{safety_gate.code}；未执行检索或外部调用")
            return PipelineResult(
                question=question,
                mode=canonical_mode,
                answer=refusal_answer(safety_gate),
                entries=[],
                citation_check=None,
                trace=trace,
                query_spec=spec,
                evidence_gate=safety_gate,
                used_live_api=False,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
            )

        knowledge_chunks = []
        local_chunks = []
        pdf_chunks = []
        cloud_chunks = []
        live_documents: List[Document] = []
        used_live = False

        if canonical_mode in {"hybrid", "knowledge"}:
            knowledge_chunks = self.knowledge.search(spec.local_terms, top_k=12)
            trace.append(f"知识页召回 {len(knowledge_chunks)} 个 claim")
        if canonical_mode in {"hybrid", "rag"}:
            local_chunks = self.local_corpus.search(spec.local_terms, top_k=14)
            trace.append(f"本地文献快照召回 {len(local_chunks)} 个 chunk")
            pdf_chunks = self.pdf_corpus.search(spec.local_terms, top_k=18)
            if self.pdf_corpus.size:
                trace.append(
                    f"500 篇 PDF 本地库召回 {len(pdf_chunks)} 个全文/摘要 chunk"
                )
            else:
                trace.append("PDF 本地索引未建立，跳过 500 篇文献库")
            if self.supabase_corpus:
                try:
                    cloud_chunks = self.supabase_corpus.search(
                        spec.local_terms,
                        top_k=self.settings.lexical_retrieve_k,
                    )
                    trace.append(f"Supabase 云端语料召回 {len(cloud_chunks)} 个 chunk")
                except SupabaseStoreError as error:
                    trace.append(f"Supabase 云端语料不可用，已使用本地兜底：{error}")
            elif self.supabase_configuration_error:
                trace.append(f"Supabase 云端语料未启用：{self.supabase_configuration_error}")

        static_chunks, retrieval_status = self._select_static_candidates(
            spec,
            canonical_mode,
            knowledge_chunks,
            local_chunks,
            pdf_chunks,
            cloud_chunks,
            trace,
        )
        preliminary = legacy_rerank(
            question,
            build(chunks=static_chunks),
            top_k=self.settings.top_k,
        )
        local_confident = bool(preliminary and preliminary[0].score >= self.settings.pre_refusal_threshold)

        should_call_live = live_enabled and (canonical_mode == "rag" or spec.needs_latest)
        if live_enabled and canonical_mode == "hybrid" and not local_confident:
            should_call_live = True
        if should_call_live and not spec.out_of_scope:
            used_live = True
            live_documents = self._live_documents(spec, trace)
        elif live_enabled and canonical_mode == "hybrid" and local_confident and not spec.needs_latest:
            trace.append("本地/指南相关性达标，按优先级规则跳过实时 API")
        elif not live_enabled:
            trace.append("实时 API 已关闭，使用离线快照兜底")

        pooled = build(docs=live_documents, chunks=static_chunks)
        ranked = self.reranker.rerank(question, pooled, top_k=len(pooled))
        rerank_status = self.reranker.status
        if self.settings.rerank_backend not in {"deterministic", "cross_encoder"}:
            rerank_status = BackendStatus(
                requested=self.settings.rerank_backend,
                actual="deterministic",
                degraded=True,
                reason=f"不支持的 RERANK_BACKEND={self.settings.rerank_backend}",
            )
        if rerank_status.degraded:
            trace.append(
                f"{rerank_status.requested} 重排不可用，已降级为 "
                f"{rerank_status.actual}：{rerank_status.reason}"
            )
        if retrieval_profile == "degraded":
            entries = list(reversed(ranked[-self.settings.top_k :]))
            assign_citation_numbers(entries)
            trace.append("评估模式：使用低相关候选构造劣化 RAG")
        else:
            entries = ranked[: self.settings.top_k]
            assign_citation_numbers(entries)
        trace.append(f"统一候选池重排后保留 {len(entries)} 条可引用证据")
        trace.append(
            f"实际后端：检索={retrieval_status.actual}，重排={rerank_status.actual}"
        )
        degradation_reasons = [
            status.reason
            for status in (retrieval_status, rerank_status)
            if status.degraded and status.reason
        ]

        evidence_gate = assess_evidence(
            spec,
            entries,
            self.settings.pre_refusal_threshold,
            getattr(self.settings, "minimum_independent_sources", 3),
        )
        if evidence_gate.refused:
            answer = refusal_answer(evidence_gate)
            trace.append(f"触发证据门控：{evidence_gate.code}；未调用生成器")
            return PipelineResult(
                question=question,
                mode=canonical_mode,
                answer=answer,
                entries=entries,
                citation_check=None,
                trace=trace,
                query_spec=spec,
                evidence_gate=evidence_gate,
                used_live_api=used_live,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                retrieval_backend=retrieval_status.actual,
                rerank_backend=rerank_status.actual,
                degraded=bool(degradation_reasons),
                degradation_reasons=degradation_reasons,
            )

        generation_entries = select_complementary(
            entries,
            max_items=getattr(self.settings, "generation_top_k", 5),
        )
        trace.append(
            "互补证据包："
            + "、".join(
                f"[{entry.citation_number}]{entry.evidence_role}" for entry in generation_entries
            )
        )
        answer = generate(spec.safe_query or question, generation_entries, self.settings)
        trace.append(f"结构化生成完成：{answer.generator}")
        if answer.refused:
            trace.append("生成器返回 refused=true，跳过引用校验")
            check = None
            post_gate = EvidenceGateResult(
                refused=True,
                code=answer.refusal_code or "GENERATOR_REFUSAL",
                reason=answer.reason or "生成器判断现有证据不足。",
                found=answer.found,
                missing=answer.missing,
                next_steps=answer.next_steps,
            )
            answer = refusal_answer(post_gate, generator=answer.generator)
        else:
            check = verify(answer, entries)
            trace.append(f"引用校验完成：失败比例 {check.failure_ratio:.0%}")
            answer = sanitize_answer(answer, check)
            if answer.removed_paragraph_count or check.removed_citation_count:
                trace.append(
                    f"输出净化：删除 {answer.removed_paragraph_count} 条无支持陈述、"
                    f"{check.removed_citation_count} 个不可用引用"
                )
            post_gate = assess_post(check, answer, self.settings.post_failure_threshold)
            if post_gate.refused:
                answer = refusal_answer(post_gate, generator=answer.generator)
                trace.append(f"触发后置拒答：{post_gate.code}")

        return PipelineResult(
            question=question,
            mode=canonical_mode,
            answer=answer,
            entries=entries,
            citation_check=check,
            trace=trace,
            query_spec=spec,
            evidence_gate=post_gate if answer.refused else evidence_gate,
            generation_entry_ids=[entry.id for entry in generation_entries],
            used_live_api=used_live,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            retrieval_backend=retrieval_status.actual,
            rerank_backend=rerank_status.actual,
            degraded=bool(degradation_reasons),
            degradation_reasons=degradation_reasons,
        )
