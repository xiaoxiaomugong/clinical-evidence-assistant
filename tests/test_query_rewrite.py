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


def test_identity_number_suffix_is_detected_and_redacted():
    for label in ("身份证", "身份证号", "身份证号码", "证件号", "证件号码"):
        spec = rewrite(f"患者张三，{label}110101199001011234，高血压应该使用什么药？")
        assert spec.contains_phi, label
        assert "110101199001011234" not in spec.safe_query
        assert all("110101199001011234" not in text
                   for text in spec.local_terms + spec.api_queries)
