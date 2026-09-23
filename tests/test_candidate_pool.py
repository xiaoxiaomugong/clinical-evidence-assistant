from dataclasses import replace

import pytest

from evidence_assistant.candidate_pool import build
from evidence_assistant.schemas import Chunk, SourceCitation


def chunk(id, doc_id="pmid:12345678", text="Original evidence", source="pubmed_snapshot", score=0.5):
    return Chunk(id=id, doc_id=doc_id, source=source, title="Study", text=text,
                 evidence_level="RCT", retrieval_score=score,
                 citations=[SourceCitation(type="pmid", source="pubmed", pmid="12345678")])


def test_original_and_distinct_claims_survive_same_family():
    items = [chunk("original"), chunk("claim1", "page:a", "Claim one", "knowledge_page"),
             chunk("claim2", "page:a", "Claim two", "knowledge_page")]
    result = build(chunks=items, policy="source_preserving")
    assert {x.id for x in result} == {"original", "claim1", "claim2"}


def test_full_text_and_document_identity_prevent_false_merges():
    first = chunk("a", text="x" * 600 + " benefit")
    tail = replace(first, id="b", text="x" * 600 + " no benefit")
    other_doc = replace(first, id="c", doc_id="pmid:87654321", citations=[])
    assert {x.id for x in build(chunks=[first, tail, other_doc], policy="source_preserving")} == {"a", "b", "c"}


def test_same_id_highest_score_wins_independent_of_arrival():
    low = chunk("a", score=0.1)
    high = replace(low, retrieval_score=0.9)
    for items in ([low, high], [high, low]):
        result = build(chunks=items, policy="source_preserving")
        assert len(result) == 1
        assert result[0].retrieval_score == 0.9


def test_duplicate_text_retains_provenance_and_stable_survivor():
    a, b = chunk("a"), chunk("b")
    events = []
    result = build(chunks=[b, a], policy="source_preserving", on_decision=events.append)
    assert [x.id for x in result] == ["a"]
    assert any(e["entry_id"] == "b" and e["survivor_id"] == "a" and e["reason"] == "duplicate_text" for e in events)


def test_identity_collision_is_quarantined_not_overwritten():
    a = chunk("same")
    b = replace(a, doc_id="pmid:87654321", citations=[], retrieval_score=0.9)
    events = []
    assert build(chunks=[a, b], policy="source_preserving", on_decision=events.append) == []
    assert len([e for e in events if e["reason"] == "identity_conflict"]) == 2


def test_same_trial_different_publications_survive():
    a = chunk("a")
    b = replace(a, id="b", doc_id="pmid:87654321", text="Secondary analysis")
    a.citations = [SourceCitation(type="trial", source="registry", nct_id="NCT12345678")]
    b.citations = list(a.citations)
    assert {x.doc_id for x in build(chunks=[a, b], policy="source_preserving")} == {"pmid:12345678", "pmid:87654321"}


def test_invalid_policy_does_not_silently_use_legacy():
    with pytest.raises(ValueError, match="policy"):
        build(chunks=[], policy="typo")


@pytest.mark.parametrize("kind", ["doi", "nct"])
def test_document_alias_conflicts_are_quarantined_across_chunks(kind):
    rows = [replace(chunk(str(n)), text=f"Evidence {n}") for n in range(3)]
    for n, row in enumerate(rows):
        if kind == 'doi':
            row.doc_id = 'doi:10.1234/primary'
            row.url = 'https://doi.org/10.1234/primary'
            row.citations = [SourceCitation(type='doi', source='journal', doi=f'10.1234/other{n}')]
        else:
            row.citations = [SourceCitation(type='trial', source='registry', nct_id=f'NCT1234567{n}')]
    events = []
    assert build(chunks=rows, policy='source_preserving', on_decision=events.append) == []
    assert len(events) == 3
    assert all(e['reason'] == 'identity_conflict' for e in events)
