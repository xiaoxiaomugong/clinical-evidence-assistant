from dataclasses import replace

import pytest

from config import settings
from evidence_assistant.candidate_pool import research_family_id
from evidence_assistant.index_registry import DenseIndexError, IndexRegistry
from evidence_assistant.pipeline import EvidencePipeline
from evidence_assistant.query_rewrite import rewrite
from evidence_assistant.rerankers import CrossEncoderReranker
from evidence_assistant.retrievers import DenseRetriever, HybridRetriever, PrecomputedRetriever
from evidence_assistant.schemas import Chunk, Entry, SourceCitation


def chunk(chunk_id: str, source: str = "pubmed_snapshot", score: float = 0.5) -> Chunk:
    return Chunk(
        id=chunk_id,
        doc_id=chunk_id.split(":chunk", 1)[0],
        source=source,
        title=chunk_id,
        text=f"Evidence text for {chunk_id}",
        evidence_level="RCT",
        retrieval_score=score,
    )


class FakeEncoder:
    def __init__(self):
        self.calls = []

    def encode(self, texts):
        self.calls.append(list(texts))
        return [[1.0, 0.0] if index == 0 else [0.0, 1.0] for index, _ in enumerate(texts)]


class FakeIndex:
    def __init__(self, first, second, third):
        self.first = first
        self.second = second
        self.third = third

    def search(self, vector, top_k, allowed_sources=None):
        if vector[0] == 1.0:
            ranked = [(self.first, 0.95), (self.second, 0.80)]
        else:
            ranked = [(self.second, 0.98), (self.third, 0.75)]
        if allowed_sources:
            ranked = [item for item in ranked if item[0].source in allowed_sources]
        return ranked[:top_k]


def test_dense_retriever_fuses_separate_query_variants(tmp_path):
    first = chunk("pmid:1:chunk:1")
    second = chunk("pmid:2:chunk:1")
    third = chunk("kp:1:chunk:1", source="knowledge_page")
    encoder = FakeEncoder()
    retriever = DenseRetriever(
        registry=IndexRegistry(tmp_path),
        corpus_version="test",
        model_name="fake-model",
        encoder=encoder,
        index=FakeIndex(first, second, third),
    )

    results = retriever.search(
        rewrite("他汀相关肌肉症状的证据是什么？"),
        top_k=5,
        allowed_sources={"pubmed_snapshot"},
    )

    assert len(encoder.calls[0]) >= 2
    assert [item.id for item in results] == [second.id, first.id]
    assert all(item.source == "pubmed_snapshot" for item in results)
    assert retriever.status.actual == "dense"
    assert not retriever.status.degraded


def test_hybrid_retriever_rrf_fuses_and_deduplicates():
    first = chunk("pmid:1:chunk:1", score=0.8)
    second = chunk("pmid:2:chunk:1", score=0.7)
    third = chunk("pmid:3:chunk:1", score=0.9)
    retriever = HybridRetriever([
        PrecomputedRetriever([first, second]),
        PrecomputedRetriever([third, first], backend_name="dense"),
    ])

    results = retriever.search(rewrite("statin muscle symptoms"), top_k=3)

    assert results[0].id == first.id
    assert {item.id for item in results} == {first.id, second.id, third.id}
    assert retriever.status.actual == "hybrid"
    assert not retriever.status.degraded


class FakeCrossEncoder:
    def predict(self, pairs, batch_size, show_progress_bar):
        del batch_size, show_progress_bar
        return [5.0 if "preferred" in passage else -5.0 for _, passage in pairs]


class BrokenCrossEncoder:
    def predict(self, pairs, batch_size, show_progress_bar):
        del pairs, batch_size, show_progress_bar
        raise RuntimeError("model runtime unavailable")


class PositiveCrossEncoder:
    def predict(self, pairs, batch_size, show_progress_bar):
        del batch_size, show_progress_bar
        return [5.0 for _ in pairs]


def entry(entry_id: str, text: str) -> Entry:
    return Entry(
        id=entry_id,
        doc_id=entry_id,
        source="pubmed_snapshot",
        title=entry_id,
        text=text,
        evidence_level="RCT",
        retrieval_score=0.5,
    )


def test_cross_encoder_reranks_candidates():
    reranker = CrossEncoderReranker("fake", model=FakeCrossEncoder())
    results = reranker.rerank(
        "clinical question",
        [entry("ordinary", "ordinary evidence"), entry("preferred", "preferred evidence")],
        top_k=2,
    )

    assert results[0].id == "preferred"
    assert reranker.status.actual == "cross_encoder"
    assert not reranker.status.degraded


def test_cross_encoder_failure_falls_back_to_deterministic():
    reranker = CrossEncoderReranker("fake", model=BrokenCrossEncoder())
    results = reranker.rerank(
        "clinical question",
        [entry("one", "first evidence"), entry("two", "second evidence")],
        top_k=2,
    )

    assert len(results) == 2
    assert reranker.status.actual == "deterministic"
    assert reranker.status.degraded
    assert "unavailable" in reranker.status.reason


def test_pipeline_records_dense_index_fallback(tmp_path):
    cfg = replace(
        settings,
        retrieval_backend="dense",
        embedding_model="missing-local-model",
        vector_index_path=tmp_path,
        enable_live_apis=False,
    )

    result = EvidencePipeline(cfg).run("降压药应早上服用还是睡前服用？")

    assert not result.answer.refused
    assert result.retrieval_backend == "legacy"
    assert result.degraded
    assert result.degradation_reasons
    assert any("降级为 legacy" in message for message in result.trace)


def test_pipeline_uses_hybrid_and_cross_encoder_when_available(tmp_path):
    cfg = replace(
        settings,
        retrieval_backend="hybrid",
        embedding_model="fake-model",
        vector_index_path=tmp_path,
        rerank_backend="cross_encoder",
        rerank_model="fake-reranker",
        enable_live_apis=False,
    )
    pipeline = EvidencePipeline(cfg)
    indexed_chunks = list(pipeline.knowledge.all_chunks())
    pipeline.dense_retriever = DenseRetriever(
        registry=IndexRegistry(tmp_path),
        corpus_version="test",
        model_name="fake-model",
        encoder=FakeEncoder(),
        index=FakeIndex(indexed_chunks[0], indexed_chunks[1], indexed_chunks[2]),
    )
    pipeline.reranker = CrossEncoderReranker("fake-reranker", model=PositiveCrossEncoder())

    result = pipeline.run("降压药应早上服用还是睡前服用？")

    assert not result.answer.refused
    assert result.retrieval_backend == "hybrid"
    assert result.rerank_backend == "cross_encoder"
    assert not result.degraded


def test_research_family_prefers_trial_registration():
    first = entry("pmid:10000001", "primary publication")
    second = entry("pmid:10000002", "secondary publication")
    first.citations = [
        SourceCitation(type="trial", source="registry", pmid="10000001", nct_id="NCT12345678")
    ]
    second.citations = [
        SourceCitation(type="trial", source="registry", pmid="10000002", nct_id="nct12345678")
    ]

    assert research_family_id(first) == "trial:NCT12345678"
    assert research_family_id(first) == research_family_id(second)


def test_versioned_dense_index_is_immutable_and_searchable(tmp_path):
    np = pytest.importorskip("numpy")
    registry = IndexRegistry(tmp_path)
    chunks = [chunk("pmid:1:chunk:1"), chunk("pmid:2:chunk:1")]
    embeddings = np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)

    path = registry.write("corpus-v1", "model/name", "revision-1", chunks, embeddings)
    loaded = registry.load("corpus-v1", "model/name", "revision-1")
    results = loaded.search([1.0, 0.0], top_k=1)

    assert path.exists()
    assert results[0][0].id == chunks[0].id
    with pytest.raises(DenseIndexError, match="Refusing to overwrite"):
        registry.write("corpus-v1", "model/name", "revision-1", chunks, embeddings)
