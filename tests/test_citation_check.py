from evidence_assistant.citation_check import verify
from evidence_assistant.schemas import Answer, AnswerParagraph, Entry


def entry(number=1):
    return Entry(
        id="e1",
        doc_id="pmid:12345678",
        source="pubmed_snapshot",
        title="Evidence",
        text="他汀治疗仅小幅增加肌肉症状风险。",
        evidence_level="Meta-analysis",
        url="https://pubmed.ncbi.nlm.nih.gov/12345678/",
        citation_number=number,
    )


def test_valid_extractive_mapping_passes():
    evidence = entry()
    answer = Answer(
        refused=False,
        paragraphs=[AnswerParagraph(text=evidence.text, citation_ids=[1])],
        generator="extractive",
    )
    check = verify(answer, [evidence])
    assert check.valid
    assert check.failure_ratio == 0


def test_out_of_range_citation_is_rejected():
    answer = Answer(
        refused=False,
        paragraphs=[AnswerParagraph(text="无来源结论", citation_ids=[99])],
        generator="llm:test",
    )
    check = verify(answer, [entry()])
    assert not check.valid
    assert check.failure_ratio == 1
    assert check.checked[0].mapping_valid is False
