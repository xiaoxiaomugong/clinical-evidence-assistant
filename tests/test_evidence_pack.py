from evidence_assistant.candidate_pool import canonical_source_id
from evidence_assistant.rerank import select_complementary
from evidence_assistant.schemas import Entry


def entry(number: int, level: str, role: str, text: str) -> Entry:
    return Entry(
        id=f"pmid:{10000000 + number}:chunk:1",
        doc_id=f"pmid:{10000000 + number}",
        source="pubmed_snapshot",
        title=f"Evidence {number}",
        text=text,
        evidence_level=level,
        evidence_role=role,
        url=f"https://pubmed.ncbi.nlm.nih.gov/{10000000 + number}/",
        score=1.0 - number * 0.05,
        citation_number=number,
    )


def test_complementary_pack_covers_available_roles_and_sources():
    entries = [
        entry(1, "Guideline", "overview", "指南提供总体建议。"),
        entry(2, "Review", "overview", "综述提供总体建议。"),
        entry(3, "RCT", "causal", "随机试验提供因果证据。"),
        entry(4, "Other", "boundary", "观察研究说明外推边界。"),
        entry(5, "RCT", "causal", "另一项随机试验。"),
        entry(6, "Other", "boundary", "另一项边界研究。"),
    ]

    selected = select_complementary(entries, max_items=4)

    assert {item.evidence_role for item in selected} == {"overview", "causal", "boundary"}
    assert len({canonical_source_id(item) for item in selected}) == len(selected)
    assert [item.citation_number for item in selected] == sorted(item.citation_number for item in selected)
