import pytest

from config import settings
from evidence_assistant.knowledge_base import KnowledgeBase
from evidence_assistant.query_rewrite import rewrite
from evidence_assistant.retrievers.hybrid import LocalCorpus
from evidence_assistant.retrievers.pdf_corpus import PdfCorpus
from scripts.sync_supabase import write_snapshot


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


def test_local_corpus_reloads_snapshot_with_retrieved_at(tmp_path):
    class SnapshotAPI:
        @staticmethod
        def fetch_active_documents():
            return [
                {
                    "id": "pmid:1",
                    "source_id": "pubmed_snapshot",
                    "title": "Evidence title",
                    "abstract": "Evidence abstract",
                    "journal": "Journal",
                    "published_year": 2026,
                    "authors": ["Researcher"],
                    "study_type": "RCT",
                    "status": None,
                    "evidence_level": "RCT",
                    "url": "https://example.test/1",
                    "topic": "hypertension",
                    "retrieved_at": "2026-08-12T01:02:03+00:00",
                }
            ]

    snapshot = tmp_path / "pulled.json"
    write_snapshot(SnapshotAPI(), snapshot)

    corpus = LocalCorpus(snapshot)

    assert corpus.size == 1
    assert corpus.documents[0].retrieved_at == "2026-08-12T01:02:03+00:00"


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
