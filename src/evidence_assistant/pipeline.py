from __future__ import annotations

import time
from dataclasses import asdict
from typing import Dict, List, Optional, Set, Tuple

import requests

from .config import Settings, settings
from .candidate_pool import build
from .answer_relevance import QuestionFocus, partition
from .citation_check import sanitize_answer, verify
from .generate import generate
from .index_registry import IndexRegistry
from .interfaces import BackendStatus
from .observability import RunObserver
from .output_policy import sanitize_generated_metadata
from .knowledge_base import KnowledgeBase
from .query_rewrite import rewrite
from .refusal import assess_evidence, assess_post, assess_safety, refusal_answer
from .rerank import assign_citation_numbers, rerank as legacy_rerank, score_details, select_complementary, select_top_k
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
from .schemas import Chunk, DependencyState, Document, EvidenceGateResult, PipelineResult, QuerySpec
from .retrievers.common import dependency_error_code
from .retrievers.hybrid import document_to_chunks


MODE_LABELS = {
    "混合模式": "hybrid",
    "知识页优先": "knowledge",
    "RAG 优先": "rag",
    "hybrid": "hybrid",
    "knowledge": "knowledge",
    "rag": "rag",
}

_DEFAULT_RECORDER = object()
_LIVE_DEPENDENCIES = ("pubmed", "europepmc", "clinicaltrials")


class EvidencePipeline:
    def __init__(self, cfg: Settings = settings, *, recorder=None):
        started = time.perf_counter()
        if cfg.candidate_pool_policy not in {"legacy", "source_preserving"}:
            raise ValueError("Invalid candidate pool policy")
        if cfg.top8_selection_policy not in {"legacy", "document_diverse"}:
            raise ValueError("Invalid Top-8 selection policy")
        self.recorder = recorder
        self.settings = cfg
        self.settings.ensure_directories()
        self.knowledge = KnowledgeBase(cfg.knowledge_dir)
        self.local_corpus = LocalCorpus(cfg.local_corpus_path)
        self.pdf_corpus = PdfCorpus(cfg.pdf_index_path)
        self.supabase_corpus = None
        self.supabase_configuration_error = ""
        if cfg.enable_supabase:
            if not cfg.supabase_url or not cfg.supabase_publishable_key:
                self.supabase_configuration_error = "configuration_error"
            else:
                try:
                    self.supabase_corpus = SupabaseCorpus(
                        cfg.supabase_url,
                        cfg.supabase_publishable_key,
                        timeout=cfg.supabase_timeout,
                    )
                except ValueError:
                    self.supabase_configuration_error = "configuration_error"
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
        if recorder:
            recorder("timing", {"stage": "initialization", "status": "success",
                                "elapsed_ms": (time.perf_counter()-started)*1000})

    def _assess_top8_evidence(self, spec, entries):
        return assess_evidence(spec, entries, self.settings.pre_refusal_threshold,
                               self.settings.minimum_independent_sources)

    def _assess_generation_evidence(self, spec, entries):
        # Historical bypass is restricted to the isolated evaluation worker.
        return assess_evidence(spec, entries, self.settings.pre_refusal_threshold,
                               self.settings.minimum_independent_sources)

    def _build_pool(self, observer, phase, chunks, docs=()):
        expanded = list(chunks)
        for doc in docs:
            expanded.extend(document_to_chunks(doc))
        observer.candidates("pool_before", expanded, phase=phase)
        callback = (lambda decision: observer.emit("candidate_decision", phase=phase, **decision)) if observer.capture_content else None
        pool = observer.call("preliminary_pool" if phase == "preliminary" else "pool", build,
                             chunks=expanded, policy=self.settings.candidate_pool_policy, on_decision=callback)
        observer.candidates("pool_after", pool, phase=phase)
        return pool

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
            reason = "retrieval_backend_invalid"
            trace.append(f"检索后端配置无效，已降级为 legacy：{reason}")
            return legacy_chunks, BackendStatus(
                requested="invalid",
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
                reason="retrieval_backend_unavailable",
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

    def _live_documents(self, spec, trace: List[str], dependency_states=None) -> List[Document]:
        documents: List[Document] = []
        retrievers = [
            ("pubmed", "PubMed", pubmed_search),
            ("europepmc", "Europe PMC", europepmc_search),
            ("clinicaltrials", "ClinicalTrials.gov", clinicaltrials_search),
        ]
        for key, label, retriever in retrievers:
            started = time.perf_counter()
            state = DependencyState(actual_backend=key)
            try:
                found = retriever(spec, top_k=4, cfg=self.settings)
                documents.extend(found)
                state.status = "success" if found else "empty"
                state.reason_code = "completed" if found else "no_results"
                state.result_count = len(found)
                trace.append(f"{label} 返回 {len(found)} 条")
            except Exception as error:
                state.status = "error"
                state.reason_code = dependency_error_code(error)
                # The fixed Timeout label preserves the existing public trace
                # contract without including any exception text.
                reason_label = "Timeout" if state.reason_code == "timeout" else state.reason_code
                trace.append(f"{label} 不可用，已降级：{reason_label}")
            finally:
                state.elapsed_ms = max(0, int((time.perf_counter() - started) * 1000))
                if dependency_states is not None:
                    dependency_states[key] = state
        return documents

    def run(
        self,
        question: str,
        mode: str = "hybrid",
        enable_live_apis: Optional[bool] = None,
        retrieval_profile: str = "normal",
        *,
        recorder=_DEFAULT_RECORDER,
    ) -> PipelineResult:
        observer = RunObserver(self.recorder if recorder is _DEFAULT_RECORDER else recorder)
        started = time.perf_counter()
        status = "success"
        try:
            result = self._run(question, mode, enable_live_apis, retrieval_profile, observer)
            observer.answer("final", result.answer)
            return result
        except Exception as error:
            status = "error"
            observer.emit("error", error_type=type(error).__name__)
            raise
        finally:
            observer.emit("timing", stage="full_pipeline", status=status,
                          elapsed_ms=(time.perf_counter()-started)*1000)
            observer.finish()

    def _run(self, question, mode, enable_live_apis, retrieval_profile, observer):
        started = time.perf_counter()
        canonical_mode = MODE_LABELS.get(mode, "hybrid")
        live_enabled = self.settings.enable_live_apis if enable_live_apis is None else enable_live_apis
        dependency_states: Dict[str, DependencyState] = {
            key: DependencyState(status="not_attempted" if live_enabled else "disabled",
                                 reason_code="not_started" if live_enabled else "disabled")
            for key in _LIVE_DEPENDENCIES
        }
        dependency_states["supabase"] = DependencyState(
            status="not_attempted" if self.settings.enable_supabase else "disabled",
            reason_code="not_started" if self.settings.enable_supabase else "disabled")
        dependency_states["generator"] = DependencyState()
        trace = ["查询改写：规则词典 + 中英文同义扩展"]
        with observer.measure("rewrite_safety"):
            spec = rewrite(question)
            safety_gate = assess_safety(spec)
        trace.append(f"识别领域：{'、'.join(spec.domains) if spec.domains else '未命中'}")
        if spec.expected_evidence_types:
            trace.append(f"预期证据类型：{'、'.join(spec.expected_evidence_types)}")

        if safety_gate.refused:
            for state in dependency_states.values():
                state.status, state.reason_code = "not_attempted", "safety_gate"
            trace.append(f"触发前置拒答/安全门控：{safety_gate.code}；未执行检索或外部调用")
            return PipelineResult(
                question="[redacted]" if safety_gate.code == "PHI_BLOCKED" else question,
                mode=canonical_mode,
                answer=refusal_answer(safety_gate),
                entries=[],
                citation_check=None,
                trace=trace,
                query_spec=None if safety_gate.code == "PHI_BLOCKED" else spec,
                evidence_gate=safety_gate,
                used_live_api=False,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                dependency_states=dependency_states,
            )

        knowledge_chunks = []
        local_chunks = []
        pdf_chunks = []
        cloud_chunks = []
        live_documents: List[Document] = []
        used_live = False

        if canonical_mode in {"hybrid", "knowledge"}:
            knowledge_chunks = observer.call("knowledge_retrieval", self.knowledge.search, spec.local_terms, top_k=12)
            trace.append(f"知识页召回 {len(knowledge_chunks)} 个 claim")
        if canonical_mode in {"hybrid", "rag"}:
            local_chunks = observer.call("snapshot_retrieval", self.local_corpus.search, spec.local_terms, top_k=14)
            trace.append(f"本地文献快照召回 {len(local_chunks)} 个 chunk")
            pdf_chunks = observer.call("pdf_retrieval", self.pdf_corpus.search, spec.local_terms, top_k=18)
            if self.pdf_corpus.size:
                trace.append(
                    f"500 篇 PDF 本地库召回 {len(pdf_chunks)} 个全文/摘要 chunk"
                )
            else:
                trace.append("PDF 本地索引未建立，跳过 500 篇文献库")
            if self.supabase_corpus:
                cloud_started = time.perf_counter()
                cloud_state = DependencyState(actual_backend="supabase")
                try:
                    cloud_chunks = observer.call("cloud_retrieval", self.supabase_corpus.search,
                        spec.local_terms,
                        top_k=self.settings.lexical_retrieve_k,
                    )
                    trace.append(f"Supabase 云端语料召回 {len(cloud_chunks)} 个 chunk")
                    cloud_state.status = "success" if cloud_chunks else "empty"
                    cloud_state.reason_code = "completed" if cloud_chunks else "no_results"
                    cloud_state.result_count = len(cloud_chunks)
                except Exception as error:
                    cloud_state.status = "error"
                    cloud_state.reason_code = dependency_error_code(error)
                    trace.append(f"Supabase 云端语料不可用，已使用本地兜底：{cloud_state.reason_code}")
                finally:
                    cloud_state.elapsed_ms = max(0, int((time.perf_counter() - cloud_started) * 1000))
                    dependency_states["supabase"] = cloud_state
            elif self.supabase_configuration_error:
                dependency_states["supabase"] = DependencyState(status="error", reason_code="configuration_error")
                trace.append("Supabase 云端语料配置不可用，已使用本地兜底：configuration_error")
        elif self.settings.enable_supabase:
            dependency_states["supabase"].reason_code = "mode_excluded"

        for branch, chunks in (("knowledge", knowledge_chunks), ("snapshot", local_chunks), ("pdf", pdf_chunks), ("cloud", cloud_chunks)):
            observer.candidates("retrieved", chunks, branch=branch)
        static_chunks, retrieval_status = observer.call("static_selection", self._select_static_candidates,
            spec,
            canonical_mode,
            knowledge_chunks,
            local_chunks,
            pdf_chunks,
            cloud_chunks,
            trace,
        )
        preliminary_pool = self._build_pool(observer, "preliminary", static_chunks)
        preliminary = observer.call("preliminary_rerank", legacy_rerank, question, preliminary_pool, top_k=len(preliminary_pool))
        preliminary = select_top_k(preliminary, self.settings.top_k, self.settings.top8_selection_policy)
        local_confident = bool(preliminary and preliminary[0].score >= self.settings.pre_refusal_threshold)

        should_call_live = live_enabled and (canonical_mode == "rag" or spec.needs_latest)
        if live_enabled and canonical_mode == "hybrid" and not local_confident:
            should_call_live = True
        if should_call_live and not spec.out_of_scope:
            used_live = True
            live_documents = observer.call("live_retrieval", self._live_documents, spec, trace, dependency_states)
            observer.candidates("retrieved", [c for d in live_documents for c in document_to_chunks(d)], branch="live")
        elif live_enabled and canonical_mode == "hybrid" and local_confident and not spec.needs_latest:
            for key in _LIVE_DEPENDENCIES:
                dependency_states[key].reason_code = "local_evidence_sufficient"
            trace.append("本地/指南相关性达标，按优先级规则跳过实时 API")
        elif not live_enabled:
            trace.append("实时 API 已关闭，使用离线快照兜底")
        else:
            for key in _LIVE_DEPENDENCIES:
                dependency_states[key].reason_code = "mode_excluded"

        pooled = self._build_pool(observer, "final", static_chunks, live_documents)
        ranked = observer.call("rerank", self.reranker.rerank, question, pooled, top_k=len(pooled))
        rerank_status = self.reranker.status
        if self.settings.rerank_backend not in {"deterministic", "cross_encoder"}:
            rerank_status = BackendStatus(
                requested="invalid",
                actual="deterministic",
                degraded=True,
                reason="rerank_backend_invalid",
            )
        if rerank_status.degraded:
            if rerank_status.reason != "rerank_backend_invalid":
                rerank_status = BackendStatus(requested="cross_encoder", actual="deterministic", degraded=True,
                                              reason="rerank_backend_unavailable")
            trace.append(
                f"{rerank_status.requested} 重排不可用，已降级为 "
                f"{rerank_status.actual}：{rerank_status.reason}"
            )
        details = score_details(question, pooled) if observer.capture_content and rerank_status.actual == "deterministic" else None
        observer.candidates("reranked", ranked, score_components=details)
        if retrieval_profile == "degraded":
            entries = list(reversed(ranked[-self.settings.top_k :]))
            assign_citation_numbers(entries)
            trace.append("评估模式：使用低相关候选构造劣化 RAG")
        else:
            callback = (lambda decision: observer.emit("candidate_decision", phase="top8", **decision)) if observer.capture_content else None
            entries = observer.call("top8_selection", select_top_k, ranked, self.settings.top_k,
                                    self.settings.top8_selection_policy, on_decision=callback)
        observer.candidates("top8", entries, policy=self.settings.top8_selection_policy)
        trace.append(f"统一候选池重排后保留 {len(entries)} 条可引用证据")
        trace.append(
            f"实际后端：检索={retrieval_status.actual}，重排={rerank_status.actual}"
        )
        degradation_reasons = [
            status.reason
            for status in (retrieval_status, rerank_status)
            if status.degraded and status.reason
        ]
        degradation_reasons.extend(
            f"{key}:{state.reason_code}" for key, state in dependency_states.items()
            if state.status in {"error", "fallback"}
        )

        direct_entries, background_entries = observer.call("question_coverage", partition, spec, entries)
        observer.candidates("question_direct", direct_entries)
        observer.candidates("question_background", background_entries)
        if not direct_entries:
            coverage_gate = EvidenceGateResult(
                refused=True, code="QUESTION_NOT_COVERED",
                reason="当前证据未直接覆盖问题中的关键干预、比较对象、结局或人群条件。",
                found=["仅找到同领域或背景材料。"] if background_entries else [],
                missing=["缺少能直接回答本次问题的可回查证据。"],
                next_steps=["核对关键术语与 PICO 条件，并补查直接相关的原始资料。"],
            )
            trace.append("关键问题覆盖不足；未调用生成器")
            return PipelineResult(
                question=question, mode=canonical_mode, answer=refusal_answer(coverage_gate), entries=entries,
                citation_check=None, trace=trace, query_spec=spec, evidence_gate=coverage_gate,
                used_live_api=used_live, elapsed_ms=int((time.perf_counter()-started)*1000),
                retrieval_backend=retrieval_status.actual, rerank_backend=rerank_status.actual,
                degraded=bool(degradation_reasons), degradation_reasons=degradation_reasons,
            )
        relevant_entries = sorted(direct_entries + background_entries, key=lambda entry: entry.citation_number)
        evidence_gate = observer.call("evidence_gate", self._assess_top8_evidence, spec, relevant_entries)
        if evidence_gate.refused:
            dependency_states["generator"].reason_code = "evidence_gate"
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
                dependency_states=dependency_states,
            )

        generation_entries = observer.call("generation_selection", select_complementary,
            relevant_entries,
            max_items=getattr(self.settings, "generation_top_k", 5),
        )
        observer.candidates("generation_top5", generation_entries)
        generation_gate = observer.call("generation_gate", self._assess_generation_evidence, spec, generation_entries)
        if generation_gate.refused:
            dependency_states["generator"].reason_code = "generation_gate"
            trace.append(f"生成证据包门控：{generation_gate.code}；未调用生成器")
            return PipelineResult(
                question=question, mode=canonical_mode, answer=refusal_answer(generation_gate), entries=entries,
                citation_check=None, trace=trace, query_spec=spec, evidence_gate=generation_gate,
                generation_entry_ids=[entry.id for entry in generation_entries], used_live_api=used_live,
                elapsed_ms=int((time.perf_counter()-started)*1000), retrieval_backend=retrieval_status.actual,
                rerank_backend=rerank_status.actual, degraded=bool(degradation_reasons), degradation_reasons=degradation_reasons,
                dependency_states=dependency_states,
            )
        trace.append(
            "互补证据包："
            + "、".join(
                f"[{entry.citation_number}]{entry.evidence_role}" for entry in generation_entries
            )
        )
        generation_started = time.perf_counter()
        answer = observer.call("generate", generate, spec.safe_query or question, generation_entries, self.settings)
        dependency_states["generator"] = answer.generation_state or DependencyState(
            status="success", reason_code="completed" if self.settings.llm_api_key else "offline_extractive",
            elapsed_ms=max(0, int((time.perf_counter() - generation_started) * 1000)),
            result_count=len(answer.paragraphs),
            actual_backend="llm" if answer.generator.startswith("llm:") else "extractive")
        generator_state = dependency_states["generator"]
        if generator_state.status == "fallback":
            degradation_reasons.append(f"generator:{generator_state.reason_code}")
            trace.append(f"LLM 不可用，已回退为抽取式生成：{generator_state.reason_code}")
        claim_ids = [f"claim:{i+1:04d}" for i in range(len(answer.paragraphs))]
        observer.answer("raw", answer, claim_ids)
        metadata_safe = sanitize_generated_metadata(answer)
        changed_fields = [field for field in ("reason", "refusal_code", "found", "missing", "next_steps", "limitations")
                          if getattr(answer, field) != getattr(metadata_safe, field)]
        answer = metadata_safe
        if not answer.refused:
            focus = QuestionFocus.from_spec(spec)
            before = len(answer.paragraphs)
            answer.paragraphs = [paragraph for paragraph in answer.paragraphs
                                 if focus.covers(paragraph.text)]
            answer.removed_paragraph_count += before - len(answer.paragraphs)
            if before != len(answer.paragraphs):
                trace.append(f"问题相关性检查：移除 {before-len(answer.paragraphs)} 条未覆盖关键条件的陈述")
        if changed_fields:
            observer.answer("metadata_sanitized", answer, claim_ids, replaced_auxiliary_fields=changed_fields)
        trace.append(f"结构化生成完成：{generator_state.actual_backend}")
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
            check = observer.call("verify", verify, answer, generation_entries)
            if observer.capture_content:
                observer.emit("answer", stage="checked", check=asdict(check), claim_ids=claim_ids)
            trace.append(f"引用校验完成：失败比例 {check.failure_ratio:.0%}")
            answer = observer.call("sanitize", sanitize_answer, answer, check)
            observer.answer("sanitized", answer, [claim_ids[i] for i in check.supported_paragraphs],
                            removed_claim_ids=[claim_ids[i] for i in check.stripped_paragraphs])
            if answer.removed_paragraph_count or check.removed_citation_count:
                trace.append(
                    f"输出净化：删除 {answer.removed_paragraph_count} 条无支持陈述、"
                    f"{check.removed_citation_count} 个不可用引用"
                )
            post_gate = observer.call("post_gate", assess_post, check, answer, self.settings.post_failure_threshold)
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
            dependency_states=dependency_states,
        )
