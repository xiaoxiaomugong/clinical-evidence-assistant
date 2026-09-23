from copy import deepcopy
from dataclasses import replace

import pytest

import evidence_assistant.pipeline as pipeline_module
from evidence_assistant.config import settings
from evidence_assistant.pipeline import EvidencePipeline
from evidence_assistant.refusal import assess_evidence
from evidence_assistant.rerank import select_complementary
from evidence_assistant.schemas import Answer, AnswerParagraph, Entry, QuerySpec, SourceCitation


def entry(n, doc=None, page=False, family="NCT12345678", score=None):
    return Entry(id=f"entry:{n}", doc_id=doc or f"pmid:{12345670+n}",
                 source="knowledge_page" if page else "pubmed_snapshot", title="Study",
                 text=f"Evidence {n}", evidence_level="RCT", topic="高血压",
                 score=score if score is not None else 1-n/100,
                 citations=[SourceCitation(type="trial", source="registry", nct_id=family)] if family else [])


def test_top8_limits_document_page_and_family_without_refilling_duplicates():
    from evidence_assistant.rerank import select_top_k
    rows = [entry(1,"wiki:a",True), entry(2,"wiki:a",True),entry(3), entry(4),entry(5,family="NCT87654321")]
    out = select_top_k(rows, top_k=8, policy="document_diverse")
    assert [x.id for x in out] == ["entry:1","entry:3","entry:5"]
    assert [x.citation_number for x in out] == [1,2,3]
    assert set(x.id for x in select_complementary(out,2)) <= {x.id for x in out}


def test_top8_ties_are_stable_and_bad_policy_fails_closed():
    from evidence_assistant.rerank import select_top_k
    a,b = entry(1,family="",score=.8), entry(2,family="",score=.8)
    assert [x.id for x in select_top_k([b,a],8,"document_diverse")] == ["entry:1","entry:2"]
    with pytest.raises(ValueError):
        select_top_k([a],8,"typo")


def test_unknown_id_does_not_create_independent_sources():
    rows = [entry(n,doc=f"unknown:{n}",family="") for n in (1,2,3)]
    spec=QuerySpec(original="question",pico=None,api_queries=[],local_terms=[],domains=["高血压"])
    gate=assess_evidence(spec,rows)
    assert gate.refused and gate.code=="INSUFFICIENT_SOURCES"
    assert gate.independent_source_count == 0


def test_generation_gate_checks_actual_packet_before_generator(monkeypatch,tmp_path):
    cfg=replace(settings,cache_dir=tmp_path/'cache',enable_live_apis=False,enable_supabase=False,llm_api_key="")
    pipe=EvidencePipeline(cfg)
    monkeypatch.setattr(pipeline_module,"select_complementary",lambda rows,max_items: rows[:1])
    def forbidden(*a,**k):
        pytest.fail("generator called with insufficient packet")
    monkeypatch.setattr(pipeline_module,"generate",forbidden)
    result=pipe.run("降压药应早上服用还是睡前服用？")
    assert result.answer.refused and result.answer.refusal_code=="INSUFFICIENT_SOURCES"
    assert len(result.generation_entry_ids)==1


def test_recorder_preserves_raw_and_sanitized_without_public_raw_payload(monkeypatch,tmp_path):
    events=[]
    cfg=replace(settings,cache_dir=tmp_path/'cache',enable_live_apis=False,enable_supabase=False,llm_api_key="")
    def generated(q,rows,cfg):
        return Answer(False, paragraphs=[AnswerParagraph(rows[0].text,[rows[0].citation_number]),
                                        AnswerParagraph("虚构数值 99999999%",[999])],generator="extractive")
    monkeypatch.setattr(pipeline_module,"generate",generated)
    result=EvidencePipeline(cfg,recorder=lambda e,p:events.append((e,deepcopy(p)))).run("降压药应早上服用还是睡前服用？")
    answers={p['stage']:p for e,p in events if e=='answer'}
    assert len(answers['raw']['answer']['paragraphs'])==2
    assert len(answers['sanitized']['answer']['paragraphs'])==1
    assert answers['final']['claim_ids'] == answers['sanitized']['claim_ids'] == ['claim:0001']
    assert '99999999' not in str(result.to_dict())
    assert not hasattr(result,'raw_answer')
    stages={p['stage'] for e,p in events if e=='candidates'}
    assert {'retrieved','pool_before','pool_after','reranked','top8','generation_top5'} <= stages
    assert any(p['stage']=='generate' and p['status']=='success' for e,p in events if e=='timing')


def test_phi_never_reaches_adapters_or_recorder_text(monkeypatch,tmp_path):
    events=[]
    cfg=replace(settings,cache_dir=tmp_path/'cache',enable_live_apis=True,enable_supabase=False,llm_api_key="synthetic")
    pipe=EvidencePipeline(cfg,recorder=lambda e,p:events.append((e,p)))
    def forbidden(*a,**k):
        pytest.fail("PHI reached retrieval or external generation")
    for name in ('pubmed_search','europepmc_search','clinicaltrials_search','generate'):
        monkeypatch.setattr(pipeline_module,name,forbidden)
    monkeypatch.setattr(pipe.knowledge,'search',forbidden)
    monkeypatch.setattr(pipe.local_corpus,'search',forbidden)
    monkeypatch.setattr(pipe.pdf_corpus,'search',forbidden)
    result=pipe.run("姓名：张三，病历号 A123456，高血压该怎么办？")
    assert result.answer.refusal_code=='PHI_BLOCKED'
    assert '张三' not in str(events) and 'A123456' not in str(events)
    assert not [p for e,p in events if e=='answer' and p['stage']=='raw']
    assert '张三' not in str(result.to_dict()) and 'A123456' not in str(result.to_dict())
    assert any(p['stage']=='generate' and p['status']=='not_run' and p['elapsed_ms'] is None for e,p in events if e=='timing')


def test_invalid_policy_settings_fail_before_loading_dependencies():
    with pytest.raises(ValueError,match="policy"):
        EvidencePipeline(replace(settings,candidate_pool_policy="typo"))


def test_performance_observer_can_measure_without_copying_candidate_content(tmp_path):
    events=[]
    def timing_only(event,payload):
        events.append((event,payload))
    timing_only.capture_content=False
    cfg=replace(settings,cache_dir=tmp_path/'cache',enable_live_apis=False,enable_supabase=False,llm_api_key="")
    result=EvidencePipeline(cfg,recorder=timing_only).run("降压药应早上服用还是睡前服用？")
    assert not result.answer.refused
    assert {event for event,payload in events} == {'timing'}


def test_conflicting_citations_do_not_split_one_document_into_three_sources():
    rows=[entry(n,doc='pmid:12345678',family='') for n in (1,2,3)]
    for n,row in enumerate(rows):
        row.citations=[SourceCitation(type='pmid',source='pubmed',pmid=str(22345670+n))]
    spec=QuerySpec(original='question',pico=None,api_queries=[],local_terms=[],domains=['高血压'])
    gate=assess_evidence(spec,rows)
    assert gate.refused and gate.independent_source_count <= 1


@pytest.mark.parametrize('kind', ['doi', 'nct', 'ambiguous_page'])
def test_aliases_and_page_claims_cannot_multiply_one_retrieved_document(kind):
    rows = [entry(n, doc='pmid:12345678', family='') for n in (1, 2, 3)]
    for n, row in enumerate(rows):
        if kind == 'doi':
            row.doc_id = 'doi:10.1234/primary'
            row.url = 'https://doi.org/10.1234/primary'
            row.citations = [SourceCitation(type='doi', source='journal', doi=f'10.1234/other{n}')]
        elif kind == 'nct':
            row.citations = [SourceCitation(type='trial', source='registry', nct_id=f'NCT1234567{n}')]
        else:
            row.source, row.doc_id = 'knowledge_page', 'wiki:one-page'
            row.citations = [SourceCitation(type='pmid', source='pubmed', pmid=str(22345670+m)) for m in range(3)]
    spec = QuerySpec(original='question', pico=None, api_queries=[], local_terms=[], domains=['高血压'])
    gate = assess_evidence(spec, rows)
    assert gate.refused and gate.independent_source_count <= 1
    if kind == 'ambiguous_page':
        assert gate.independent_source_count == 0


def test_publication_identifier_bridges_trial_family_and_page_citation():
    from evidence_assistant.candidate_pool import independent_source_count
    original = entry(1, doc='pmid:12345678')
    page = entry(2, doc='wiki:page', page=True, family='')
    page.citations = [SourceCitation(type='pmid', source='pubmed', pmid='12345678')]
    separate = entry(3, doc='pmid:87654321', family='')
    assert independent_source_count([original, page]) == 1
    assert independent_source_count([original, page, separate]) == 2


def test_distinct_studies_are_not_merged_via_one_page_with_separately_cited_claims():
    from evidence_assistant.candidate_pool import independent_source_count
    rows = []
    for n in range(3):
        pmid = str(22345670+n)
        original = entry(n, doc='pmid:'+pmid, family='')
        claim = entry(n+3, doc='wiki:page', page=True, family='')
        claim.citations = [SourceCitation(type='pmid', source='pubmed', pmid=pmid)]
        rows.extend([original, claim])
    assert independent_source_count(rows) == 3


def test_generator_cannot_cite_entry_outside_actual_packet(monkeypatch,tmp_path):
    cfg=replace(settings,cache_dir=tmp_path/'cache',enable_live_apis=False,enable_supabase=False,llm_api_key='')
    omitted={}
    def packet(rows,max_items):
        actual=select_complementary(rows,max_items)
        omitted['entry']=next(e for e in rows if e.id not in {x.id for x in actual})
        return actual
    def invented(q,rows,cfg):
        e=omitted['entry']
        return Answer(False,paragraphs=[AnswerParagraph(e.text,[e.citation_number])],generator='llm:test')
    monkeypatch.setattr(pipeline_module,'select_complementary',packet)
    monkeypatch.setattr(pipeline_module,'generate',invented)
    result=EvidencePipeline(cfg).run('降压药应早上服用还是睡前服用？')
    assert result.answer.refused
    assert not result.citation_check.checked[0].mapping_valid


def test_generator_refusal_cannot_leak_unchecked_recommendations(monkeypatch,tmp_path):
    cfg=replace(settings,cache_dir=tmp_path/'cache',enable_live_apis=False,enable_supabase=False,llm_api_key='')
    monkeypatch.setattr(pipeline_module,'generate',lambda *a:Answer(True,reason='建议停药，风险下降999999%',
                        found=['风险下降999999%'],next_steps=['建议停药'],generator='llm:test'))
    result=EvidencePipeline(cfg).run('降压药应早上服用还是睡前服用？')
    assert result.answer.refused
    assert '999999' not in str(result.answer) and '建议停药' not in str(result.answer)


@pytest.mark.parametrize("policy", ["legacy", "source_preserving"])
@pytest.mark.parametrize("mode,latest,score,enabled,expected_live", [
    ("hybrid", False, .19, True, False),
    ("hybrid", False, .17, True, True),
    ("hybrid", True, .19, True, True),
    ("rag", False, .19, True, True),
    ("rag", True, .17, False, False),
])
def test_preliminary_policy_and_live_decision_boundaries(
    monkeypatch, tmp_path, policy, mode, latest, score, enabled, expected_live
):
    cfg = replace(settings, cache_dir=tmp_path/'cache', enable_live_apis=enabled,
                  enable_supabase=False, llm_api_key='', candidate_pool_policy=policy,
                  top8_selection_policy='document_diverse')
    pipe = EvidencePipeline(cfg)
    builds, selections, live_calls = [], [], []
    actual_build, actual_select = pipeline_module.build, pipeline_module.select_top_k
    def build_spy(*args, **kwargs):
        builds.append(kwargs['policy'])
        return actual_build(*args, **kwargs)
    def select_spy(rows, k, selected_policy, **kwargs):
        selections.append(selected_policy)
        return actual_select(rows, k, selected_policy, **kwargs)
    monkeypatch.setattr(pipeline_module, 'build', build_spy)
    monkeypatch.setattr(pipeline_module, 'select_top_k', select_spy)
    monkeypatch.setattr(pipeline_module, 'legacy_rerank',
                        lambda *args, **kwargs: [entry(1, family='', score=score)])
    monkeypatch.setattr(pipe, '_live_documents', lambda *args: live_calls.append(True) or [])
    result = pipe.run(('最新' if latest else '') + '高血压有哪些研究证据？', mode=mode)
    assert builds == [policy, policy]
    assert selections == ['document_diverse', 'document_diverse']
    assert bool(live_calls) is expected_live
    assert result.used_live_api is expected_live


def test_live_source_timeouts_fall_back_without_echoing_error_text(monkeypatch, tmp_path):
    cfg = replace(settings, cache_dir=tmp_path/'cache', enable_live_apis=True,
                  enable_supabase=False, llm_api_key='')
    called = []
    def timeout(*args, **kwargs):
        called.append(True)
        raise pipeline_module.requests.Timeout('untrusted private error body')
    for name in ('pubmed_search', 'europepmc_search', 'clinicaltrials_search'):
        monkeypatch.setattr(pipeline_module, name, timeout)
    result = EvidencePipeline(cfg).run('最新降压药应早上服用还是睡前服用？')
    assert len(called) == 3 and result.used_live_api
    assert not result.answer.refused
    assert sum('Timeout' in line for line in result.trace) == 3
    assert 'untrusted private error body' not in str(result.to_dict())
