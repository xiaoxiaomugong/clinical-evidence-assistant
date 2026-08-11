from evidence_assistant.query_rewrite import rewrite


def test_rewrite_detects_domain_and_bilingual_terms():
    spec = rewrite("高血压患者的降压药如何选择？")
    assert "高血压" in spec.domains
    assert "hypertension antihypertensive treatment" in spec.local_terms
    assert spec.api_queries
    assert not spec.out_of_scope


def test_animal_question_is_out_of_scope():
    spec = rewrite("宠物犬高血压如何用药？")
    assert spec.out_of_scope
