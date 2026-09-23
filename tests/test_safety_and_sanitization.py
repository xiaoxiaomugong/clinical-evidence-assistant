from evidence_assistant.citation_check import sanitize_answer, verify
from evidence_assistant.pipeline import EvidencePipeline
from evidence_assistant.query_rewrite import rewrite
from evidence_assistant.refusal import assess_post
from evidence_assistant.schemas import Answer, AnswerParagraph, CitationCheck, Entry


def evidence(number: int, text: str) -> Entry:
    return Entry(
        id=f"pmid:1234567{number}:chunk:1",
        doc_id=f"pmid:1234567{number}",
        source="pubmed_snapshot",
        title="Evidence",
        text=text,
        evidence_level="RCT",
        url=f"https://pubmed.ncbi.nlm.nih.gov/1234567{number}/",
        citation_number=number,
    )


def test_numeric_claim_not_present_in_evidence_is_removed():
    entry = evidence(1, "随机试验显示收缩压平均下降 2 mmHg。")
    answer = Answer(
        refused=False,
        paragraphs=[AnswerParagraph(text="随机试验显示收缩压平均下降 8 mmHg。", citation_ids=[1])],
        generator="llm:test",
    )

    check = verify(answer, [entry])
    sanitized = sanitize_answer(answer, check)

    assert check.stripped_paragraphs == [0]
    assert check.checked[0].numeric_consistent is False
    assert sanitized.paragraphs == []
    assert sanitized.removed_paragraph_count == 1


def test_sanitization_keeps_supported_claim_and_removes_bad_citation():
    supported = evidence(1, "限钠干预与血压下降相关。")
    unrelated = evidence(2, "本研究讨论运动依从性。")
    answer = Answer(
        refused=False,
        paragraphs=[
            AnswerParagraph(text="限钠干预与血压下降相关。", citation_ids=[1, 2]),
            AnswerParagraph(text="证据证明死亡率下降 40%。", citation_ids=[2]),
        ],
        generator="llm:test",
    )

    check = verify(answer, [supported, unrelated])
    sanitized = sanitize_answer(answer, check)

    assert len(sanitized.paragraphs) == 1
    assert sanitized.paragraphs[0].citation_ids == [1]
    assert sanitized.removed_paragraph_count == 1
    assert check.removed_citation_count == 2


def test_phi_is_blocked_before_retrieval():
    result = EvidencePipeline().run("姓名：张三，病历号 A123456，高血压该怎么办？")

    assert result.answer.refused
    assert result.answer.refusal_code == "PHI_BLOCKED"
    assert result.entries == []
    assert not result.used_live_api


def test_personalized_dose_or_stop_request_is_refused():
    result = EvidencePipeline().run("我现在每天吃降压药，能不能停药？")

    assert result.answer.refused
    assert result.answer.refusal_code == "PERSONALIZED_TREATMENT"
    assert result.answer.next_steps


def test_latest_query_sets_time_and_live_refresh_intent():
    spec = rewrite("目前最新的高血压指南证据是什么？")

    assert spec.needs_latest
    assert spec.time_from is not None and spec.time_to is not None
    assert "Guideline" in spec.expected_evidence_types


def test_high_original_claim_failure_rate_refuses_even_if_one_claim_survives():
    answer = Answer(
        refused=False,
        paragraphs=[AnswerParagraph(text="一条受支持陈述。", citation_ids=[1])],
        original_paragraph_count=4,
    )
    check = CitationCheck(
        valid=False,
        failure_ratio=0.75,
        output_valid=True,
        supported_paragraphs=[0],
    )

    gate = assess_post(check, answer, failure_threshold=0.5)

    assert gate.refused
    assert gate.code == "CITATION_FAILURE"


def test_reversing_explicit_negation_is_not_supported_by_word_overlap():
    entry = evidence(1, "该干预未降低心血管风险。")
    answer = Answer(False, paragraphs=[AnswerParagraph("该干预降低心血管风险。", [1])], generator="llm:test")
    check = verify(answer, [entry])
    assert check.stripped_paragraphs == [0]
    assert sanitize_answer(answer, check).paragraphs == []


def test_same_number_with_wrong_unit_is_removed():
    entry = evidence(1, "收缩压平均下降 2 mmHg。")
    answer = Answer(False, paragraphs=[AnswerParagraph("收缩压平均下降 2 mg。", [1])], generator="llm:test")
    check = verify(answer, [entry])
    assert check.checked[0].numeric_consistent is False
    assert sanitize_answer(answer, check).paragraphs == []


def test_matching_negation_and_unit_remain_supported():
    for text in ("该干预未降低心血管风险。", "收缩压平均下降 2 mmHg。"):
        entry = evidence(1, text)
        check = verify(Answer(False, paragraphs=[AnswerParagraph(text,[1])],generator="llm:test"),[entry])
        assert check.output_valid


def test_english_negation_word_boundaries_survive_normalization():
    entry = evidence(1, "Treatment did not reduce risk.")
    check = verify(Answer(False, paragraphs=[AnswerParagraph("Treatment did reduce risk.",[1])],
                          generator="llm:test"), [entry])
    assert check.stripped_paragraphs == [0]


def test_chinese_numbers_without_spaces_still_require_matching_units():
    entry = evidence(1, "收缩压平均下降2mmHg。")
    check = verify(Answer(False, paragraphs=[AnswerParagraph("收缩压平均下降2mg。",[1])],
                          generator="llm:test"), [entry])
    assert check.checked[0].numeric_consistent is False


def test_auxiliary_fields_cannot_bypass_citation_validation():
    entry = evidence(1, "限钠干预与血压下降相关。")
    answer = Answer(False, paragraphs=[AnswerParagraph(entry.text,[1])], generator="llm:test",
                    limitations=["死亡风险下降999999%"], next_steps=["建议停药"],
                    found=["发现新疗法"], missing=["需要增加药量"], reason="建议换药")
    result = sanitize_answer(answer,verify(answer,[entry]))
    assert result.paragraphs
    assert result.next_steps == result.found == result.missing == []
    assert not result.reason
    assert '999999' not in str(result.limitations)
