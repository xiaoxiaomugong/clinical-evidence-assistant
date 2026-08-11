from __future__ import annotations

import time
from typing import List, Optional

import requests

from config import Settings, settings
from .candidate_pool import build
from .citation_check import verify
from .generate import generate
from .knowledge_base import KnowledgeBase
from .query_rewrite import rewrite
from .refusal import decide_post, decide_pre
from .rerank import rerank
from .retrievers import LocalCorpus, PdfCorpus, clinicaltrials_search, europepmc_search, pubmed_search
from .schemas import Answer, Document, PipelineResult


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
    ) -> PipelineResult:
        started = time.perf_counter()
        canonical_mode = MODE_LABELS.get(mode, "hybrid")
        live_enabled = self.settings.enable_live_apis if enable_live_apis is None else enable_live_apis
        trace = ["查询改写：规则词典 + 中英文同义扩展"]
        spec = rewrite(question)
        trace.append(f"识别领域：{'、'.join(spec.domains) if spec.domains else '未命中'}")

        knowledge_chunks = []
        local_chunks = []
        pdf_chunks = []
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

        preliminary = rerank(
            question,
            build(chunks=local_chunks + pdf_chunks, pages=knowledge_chunks),
            top_k=self.settings.top_k,
        )
        local_confident = bool(preliminary and preliminary[0].score >= self.settings.pre_refusal_threshold)

        should_call_live = live_enabled and canonical_mode == "rag"
        if live_enabled and canonical_mode == "hybrid" and not local_confident:
            should_call_live = True
        if should_call_live and not spec.out_of_scope:
            used_live = True
            live_documents = self._live_documents(spec, trace)
        elif live_enabled and canonical_mode == "hybrid" and local_confident:
            trace.append("本地/指南相关性达标，按优先级规则跳过实时 API")
        elif not live_enabled:
            trace.append("实时 API 已关闭，使用离线快照兜底")

        entries = rerank(
            question,
            build(docs=live_documents, chunks=local_chunks + pdf_chunks, pages=knowledge_chunks),
            top_k=self.settings.top_k,
        )
        trace.append(f"统一候选池重排后保留 {len(entries)} 条可引用证据")

        refused, reason = decide_pre(spec, entries, self.settings.pre_refusal_threshold)
        if refused:
            answer = Answer(refused=True, reason=reason, generator="none")
            trace.append("触发前置拒答：未调用生成器")
            return PipelineResult(
                question=question,
                mode=canonical_mode,
                answer=answer,
                entries=entries,
                citation_check=None,
                trace=trace,
                query_spec=spec,
                used_live_api=used_live,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
            )

        answer = generate(question, entries, self.settings)
        trace.append(f"结构化生成完成：{answer.generator}")
        if answer.refused:
            trace.append("生成器返回 refused=true，跳过引用校验")
            check = None
        else:
            check = verify(answer, entries)
            trace.append(f"引用校验完成：失败比例 {check.failure_ratio:.0%}")
            post_refused, post_reason = decide_post(check, answer, self.settings.post_failure_threshold)
            if post_refused:
                answer = Answer(refused=True, reason=post_reason, generator=answer.generator)
                trace.append("触发后置拒答")

        return PipelineResult(
            question=question,
            mode=canonical_mode,
            answer=answer,
            entries=entries,
            citation_check=check,
            trace=trace,
            query_spec=spec,
            used_live_api=used_live,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )
