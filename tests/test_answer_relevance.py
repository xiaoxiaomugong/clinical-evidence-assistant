"""Real offline engine checks for question coverage, not just cited support."""
from pathlib import Path
from dataclasses import replace

import pytest

from evidence_assistant.pipeline import EvidencePipeline
from evidence_assistant.config import settings


@pytest.fixture
def offline_pipeline(tmp_path):
    root = Path(__file__).resolve().parents[1]
    data = root / "data"
    cfg = replace(
        settings,
        root_dir=root, data_dir=data, cache_dir=tmp_path / "cache",
        knowledge_dir=data / "knowledge_pages",
        local_corpus_path=data / "raw" / "local_corpus.json",
        pdf_collection_dir=tmp_path / "disabled-pdf",
        pdf_index_path=tmp_path / "absent.sqlite3",
        vector_index_path=tmp_path / "indexes",
        retrieval_backend="legacy", rerank_backend="deterministic",
        candidate_pool_policy="source_preserving", top8_selection_policy="legacy",
        top_k=8, generation_top_k=5, minimum_independent_sources=3,
        pre_refusal_threshold=0.18, enable_live_apis=False,
        enable_supabase=False, llm_api_key="",
    )
    return EvidencePipeline(cfg)


def _claims(result):
    return " ".join(claim.text for claim in result.answer.paragraphs)


def test_timing_answer_keeps_direct_evidence_without_diabetes_claims(offline_pipeline):
    result = offline_pipeline.run("降压药应早上服用还是睡前服用？", enable_live_apis=False)
    assert not result.answer.refused
    assert "TIME" in _claims(result)
    assert "胰岛素" not in _claims(result)
    assert "降糖药" not in _claims(result)


def test_mediterranean_answer_excludes_sodium_and_glucose_drug_claims(offline_pipeline):
    result = offline_pipeline.run("地中海饮食与心血管风险有哪些研究证据？", enable_live_apis=False)
    assert not result.answer.refused
    assert "地中海饮食" in _claims(result)
    assert "限钠" not in _claims(result)
    assert "SGLT2" not in _claims(result)


def test_unknown_pathway_refuses_generic_guideline(offline_pipeline):
    result = offline_pipeline.run("高血压中的 ZXQZ 通路研究有何结论？", enable_live_apis=False)
    assert result.answer.refused
    assert result.answer.refusal_code == "QUESTION_NOT_COVERED"
    assert not result.answer.paragraphs


def test_comparison_and_pico_population_must_be_covered(offline_pipeline):
    comparison = offline_pipeline.run("脑卒中二级预防中阿司匹林和氯吡格雷如何比较？", enable_live_apis=False)
    # Only two independent stroke comparison sources remain after unrelated
    # diet studies are excluded; the existing three-source gate must stand.
    assert comparison.answer.refused
    assert comparison.answer.refusal_code == "INSUFFICIENT_SOURCES"
    assert "地中海饮食" not in _claims(comparison)
    missing = offline_pipeline.run("地中海饮食能改善妊娠高血压吗？\n人群：妊娠高血压\n干预：地中海饮食", enable_live_apis=False)
    assert missing.answer.refused
    assert missing.answer.refusal_code == "QUESTION_NOT_COVERED"


def test_broad_disease_question_remains_answerable(offline_pipeline):
    result = offline_pipeline.run("高血压治疗有哪些证据？", enable_live_apis=False)
    assert not result.answer.refused
    assert result.answer.paragraphs
