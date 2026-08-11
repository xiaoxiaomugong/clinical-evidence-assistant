from evidence_assistant.pipeline import EvidencePipeline


def test_pipeline_answers_with_traceable_citations():
    result = EvidencePipeline().run("降压药应早上服用还是睡前服用？")
    assert not result.answer.refused
    assert result.entries[0].id == "htn_claim_3"
    assert result.citation_check and result.citation_check.valid
    allowed = {entry.citation_number for entry in result.entries}
    assert all(set(paragraph.citation_ids) <= allowed for paragraph in result.answer.paragraphs)


def test_pipeline_refuses_fictional_drug_before_generation():
    result = EvidencePipeline().run("虚构新药 XYZ 对高血压有什么疗效？")
    assert result.answer.refused
    assert result.answer.generator == "none"
    assert result.citation_check is None
    assert any("前置拒答" in step for step in result.trace)


def test_pipeline_refuses_out_of_domain_question():
    result = EvidencePipeline().run("宠物犬高血压如何用药？")
    assert result.answer.refused
