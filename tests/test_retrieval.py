import pytest

from config import settings
from evidence_assistant.knowledge_base import KnowledgeBase
from evidence_assistant.query_rewrite import rewrite
from evidence_assistant.retrievers.hybrid import LocalCorpus
from evidence_assistant.retrievers.pdf_corpus import PdfCorpus


def test_knowledge_search_returns_timing_claim_first():
    knowledge = KnowledgeBase(settings.knowledge_dir)
    spec = rewrite("降压药早上还是睡前服用？")
    results = knowledge.search(spec.local_terms, top_k=3)
    assert results
    assert results[0].id == "htn_claim_3"


def test_local_corpus_loads_snapshot():
    corpus = LocalCorpus(settings.local_corpus_path)
    assert corpus.size >= 10
    results = corpus.search(rewrite("他汀肌肉副作用").local_terms, top_k=3)
    assert any(chunk.doc_id == "pmid:36049498" for chunk in results)


@pytest.mark.skipif(
    not settings.pdf_index_path.exists(),
    reason="Optional local PDF index is not distributed with the repository",
)
def test_pdf_collection_index_contains_500_documents():
    corpus = PdfCorpus(settings.pdf_index_path)
    assert corpus.size == 500
    assert corpus.chunk_count >= 500
    results = corpus.search(rewrite("cholesterol coronary heart disease").local_terms, top_k=5)
    assert results
    assert all(chunk.source == "pdf_collection" for chunk in results)
