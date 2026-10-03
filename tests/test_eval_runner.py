import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_new_run_refuses_existing_directory_without_modifying_it(tmp_path):
    from eval.run_p0 import create_run_directory

    output = tmp_path / "run"
    output.mkdir()
    marker = output / "keep"
    marker.write_text("original")
    with pytest.raises(FileExistsError):
        create_run_directory(output)
    assert marker.read_text() == "original"


def test_clean_environment_drops_credentials_and_forces_offline(tmp_path, monkeypatch):
    from eval.run_p0 import clean_environment

    monkeypatch.setenv("LLM_API_KEY", "synthetic-do-not-copy")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "synthetic-do-not-copy")
    monkeypatch.setenv("ENABLE_LIVE_APIS", "true")
    env = clean_environment(tmp_path, tmp_path / "cache")
    assert "synthetic-do-not-copy" not in json.dumps(env)
    assert env["EVIDENCE_ASSISTANT_ENV_FILE"] == os.devnull
    assert env["ENABLE_LIVE_APIS"] == "false"
    assert env["HF_HUB_OFFLINE"] == "1"
    assert env["PYTHONHASHSEED"] == "0"


def test_settings_are_all_explicit_and_c0_index_is_absent(tmp_path):
    from dataclasses import fields
    from evidence_assistant.config import Settings
    from eval.offline_runner import settings_values, construct_settings

    values = settings_values(tmp_path, "C0", "B1", tmp_path / "cache")
    cfg = construct_settings(Settings, values)
    assert set(values) == {field.name for field in fields(Settings)}
    assert not cfg.pdf_index_path.exists()
    assert cfg.enable_live_apis is False and cfg.enable_supabase is False
    assert cfg.llm_api_key == cfg.pubmed_api_key == cfg.supabase_secret_key == ""
    assert (cfg.top_k, cfg.generation_top_k, cfg.minimum_independent_sources) == (8, 5, 3)
    values.pop("request_timeout")
    with pytest.raises(ValueError, match="Settings fields"):
        construct_settings(Settings, values)


def test_recorder_snapshots_candidates_and_links_sanitized_claims(tmp_path):
    from eval.run_record import RunRecorder

    recorder = RunRecorder(tmp_path, "C0", "B1", 1)
    recorder.start_question("q-test")
    payload = {"stage": "pool_before", "phase": "final", "entries": [
        {"id": "a", "doc_id": "PMID:1", "text": "original", "score": 0.2}
    ]}
    recorder("candidates", payload)
    payload["entries"][0]["text"] = "mutated"
    recorder("answer", {"stage": "raw", "answer": {"paragraphs": [
        {"text": "Supported claim", "citation_ids": [1]},
        {"text": "Unsupported claim", "citation_ids": [99]}
    ]}})
    recorder("answer", {"stage": "checked", "check": {
        "supported_paragraphs": [0], "stripped_paragraphs": [1], "checked": [
            {"paragraph_index": 1, "reason": "invalid citation"}
        ]}})
    recorder("answer", {"stage": "sanitized", "answer": {"paragraphs": [
        {"text": "Supported claim", "citation_ids": [1]}
    ]}})
    recorder.finish_question()
    candidates = [json.loads(line) for line in (tmp_path / "candidates.jsonl").read_text().splitlines()]
    answers = [json.loads(line) for line in (tmp_path / "answers.jsonl").read_text().splitlines()]
    assert candidates[0]["text"] == "original"
    assert candidates[0]["question_id"] == "q-test"
    assert candidates[0]["entry_id"] == "a"
    assert answers[0]["claims"][0]["claim_id"] == answers[2]["claims"][0]["claim_id"]
    assert answers[1]["removed_claims"][0]["reason"] == "invalid citation"


def test_recorder_missing_timings_are_null_and_input_is_not_persisted(tmp_path):
    from eval.run_record import RunRecorder

    recorder = RunRecorder(tmp_path, "C0", "B1", 1)
    recorder.start_question("synthetic-phi", question="SYNTHETIC PRIVATE INPUT")
    recorder("timing", {"stage": "safety", "status": "success", "elapsed_ms": 1.0})
    recorder.finish_question()
    text = "".join(path.read_text() for path in tmp_path.glob("*.jsonl"))
    assert "SYNTHETIC PRIVATE INPUT" not in text
    timings = [json.loads(line) for line in (tmp_path / "timings.jsonl").read_text().splitlines()]
    generation = next(row for row in timings if row["stage"] == "generate")
    assert generation["status"] == "not_run" and generation["elapsed_ms"] is None


def test_status_summary_excludes_skipped_and_errors_from_quality_denominator():
    from eval.run_record import summarize_results

    summary = summarize_results([
        {"run_status": "success", "answer_status": "answered", "legacy": {"refusal_correct": True}},
        {"run_status": "skipped", "answer_status": None, "legacy": None},
        {"run_status": "error", "answer_status": None, "legacy": None},
    ])
    assert summary["status_counts"] == {"success": 1, "error": 1, "skipped": 1}
    assert summary["quality"]["refusal_accuracy"] == {"value": 1.0, "numerator": 1, "denominator": 1}
    assert summary["formal_clinical_validation"]["value"] is None


def test_semantic_comparison_ignores_only_timing_not_refusal():
    from eval.run_record import semantic_digest

    first = {"question_id": "q1", "elapsed_ms": 2, "answer": {"refused": False}, "repeat": 1}
    second = {"question_id": "q1", "elapsed_ms": 5, "answer": {"refused": False}, "repeat": 2}
    assert semantic_digest(first) == semantic_digest(second)
    second["answer"]["refused"] = True
    assert semantic_digest(first) != semantic_digest(second)


def test_network_guard_selftest_blocks_socket_in_isolated_process(tmp_path):
    from eval.run_p0 import clean_environment

    script = """from pathlib import Path
from eval.offline_runner import install_network_guard, network_selftest
events = install_network_guard()
assert network_selftest(events)['passed'] is True
assert events and all(e['phase'] == 'selftest' for e in events)
"""
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                               env=clean_environment(root, tmp_path))
    assert completed.returncode == 0, completed.stderr


def test_candidate_index_only_changes_data_arms(tmp_path):
    from eval.offline_runner import settings_values

    baseline = settings_values(tmp_path, "C1", "B1", tmp_path / "cache")
    data_arm = settings_values(tmp_path, "C1", "D1", tmp_path / "cache")
    assert baseline["pdf_index_path"].name == "pdf_collection.sqlite3"
    assert data_arm["pdf_index_path"].name == "pdf_collection_vnext.sqlite3"
    assert settings_values(tmp_path, "C1", "RD", tmp_path / "cache")["top8_selection_policy"] == "legacy"


def test_pipeline_timing_names_do_not_create_false_not_run_records(tmp_path):
    from eval.run_record import RunRecorder

    recorder = RunRecorder(tmp_path, "C0", "B1", 1)
    recorder.start_question("q-test")
    recorder("timing", {"stage": "generate", "status": "success", "elapsed_ms": 2.0})
    recorder.finish_question()
    timings = [json.loads(line) for line in (tmp_path / "timings.jsonl").read_text().splitlines()]
    assert not any(row["stage"] == "generation" and row["status"] == "not_run" for row in timings)


def test_candidates_have_separate_page_document_and_family_identity(tmp_path):
    from eval.run_record import RunRecorder

    recorder = RunRecorder(tmp_path, "C0", "R1", 1)
    recorder.start_question("q-test")
    recorder("candidates", {"stage": "pool_after", "phase": "final", "entries": [{
        "id": "page-claim", "doc_id": "page-guideline", "source": "knowledge_page", "text": "Claim",
        "citations": [{"type": "article", "source": "PubMed", "pmid": "31132793", "nct_id": None,
                       "doi": None, "chapter": None, "url": ""}]
    }]})
    row = json.loads((tmp_path / "candidates.jsonl").read_text())
    assert row["document_identity"] == "page:page-guideline"
    assert row["family_id"] == "pmid:31132793"


def test_regression_gates_reject_coverage_loss_even_when_recall_improves():
    from eval.run_p0 import engineering_gates

    baseline = {"quality": {"recall_at_8": {"value": .75}, "ndcg_at_8": {"value": .755},
                             "key_point_coverage": {"value": .8}},
                "answer_counts": {"answered": 12, "refused": 3}, "status_counts": {"success": 15, "error": 0, "skipped": 0}}
    candidate = json.loads(json.dumps(baseline))
    candidate["quality"]["recall_at_8"]["value"] = 23 / 24
    candidate["quality"]["key_point_coverage"]["value"] = .779
    gates = engineering_gates(baseline, candidate, original_pairs_retained=5)
    assert gates["retrieval_benefit"]["passed"] is True
    assert gates["coverage_regression"]["passed"] is False


def test_recorder_preserves_authoritative_claim_ids_for_duplicate_text(tmp_path):
    from eval.run_record import RunRecorder

    recorder = RunRecorder(tmp_path, "C0", "B1", 1)
    recorder.start_question("q-test")
    recorder("answer", {"stage": "raw", "claim_ids": ["claim:0001", "claim:0002"],
                         "answer": {"paragraphs": [{"text": "Same text", "citation_ids": [99]},
                                                   {"text": "Same text", "citation_ids": [1]}]}})
    recorder("answer", {"stage": "sanitized", "claim_ids": ["claim:0002"],
                         "answer": {"paragraphs": [{"text": "Same text", "citation_ids": [1]}]}})
    rows = [json.loads(line) for line in (tmp_path / "answers.jsonl").read_text().splitlines()]
    assert rows[0]["claims"][1]["claim_id"] == rows[1]["claims"][0]["claim_id"]
    assert rows[0]["claims"][0]["claim_id"] != rows[1]["claims"][0]["claim_id"]


def test_recorder_accepts_safe_pipeline_error_event(tmp_path):
    from eval.run_record import RunRecorder

    recorder = RunRecorder(tmp_path, "C0", "B1", 1)
    recorder.start_question("q-test")
    recorder("error", {"error_type": "ValueError"})
    assert json.loads((tmp_path / "answers.jsonl").read_text())["error_type"] == "ValueError"


def test_opted_in_question_storage_still_blocks_phi(tmp_path):
    from eval.run_record import RunRecorder

    recorder = RunRecorder(tmp_path, "C0", "B1", 1, allow_raw_questions=True)
    recorder.start_question("synthetic-phi", question="患者张三，身份证号110101199001011234，应该使用什么药？")
    assert "110101199001011234" not in (tmp_path / "answers.jsonl").read_text()


def test_failed_questions_count_zero_in_planned_coverage_denominator():
    from eval.run_record import summarize_results

    result = summarize_results([
        {"run_status": "success", "should_answer": True, "answer_status": "answered",
         "legacy": {"key_point_coverage": 1.0, "refusal_correct": True}},
        {"run_status": "error", "should_answer": True, "answer_status": None, "legacy": None},
        {"run_status": "skipped", "should_answer": True, "answer_status": None, "legacy": None},
    ])
    assert result["intention_to_evaluate"]["legacy_rule_key_point_coverage"] == {
        "value": .5, "numerator": 1.0, "denominator": 2}


def test_run_rejects_new_output_nested_inside_historical_artifacts(tmp_path):
    from eval.run_p0 import main

    baseline = tmp_path / "history"
    baseline.mkdir()
    with pytest.raises(SystemExit):
        main(["--baseline", str(baseline), "--output", str(baseline / "new-run"), "--profiles", "C0"])
    assert list(baseline.iterdir()) == []


def test_top8_keeps_rank_before_selection(tmp_path):
    from eval.run_record import RunRecorder

    recorder = RunRecorder(tmp_path, "C0", "R2", 1)
    recorder.start_question("q-test")
    entries = [{"id": "a", "doc_id": "pmid:31132793", "source": "pubmed_snapshot", "text": "a"},
               {"id": "b", "doc_id": "pmid:34024117", "source": "pubmed_snapshot", "text": "b"}]
    recorder("candidates", {"stage": "reranked", "entries": entries})
    recorder("candidates", {"stage": "top8", "entries": [entries[1]]})
    rows = [json.loads(line) for line in (tmp_path / "candidates.jsonl").read_text().splitlines()]
    assert rows[-1]["rank_before_selection"] == 2
    assert rows[-1]["rank_after_selection"] == 1


def test_behavior_gate_rejects_swapped_answer_and_refusal_with_same_totals():
    from eval.run_p0 import engineering_gates
    from eval.run_record import summarize_results

    baseline = summarize_results([
        {"question_id": "answerable", "run_status": "success", "should_answer": True, "answer_status": "answered"},
        {"question_id": "refusal", "run_status": "success", "should_answer": False, "answer_status": "refused"},
    ])
    candidate = summarize_results([
        {"question_id": "answerable", "run_status": "success", "should_answer": True, "answer_status": "refused"},
        {"question_id": "refusal", "run_status": "success", "should_answer": False, "answer_status": "answered"},
    ])
    gate = engineering_gates(baseline, candidate)["answer_behavior"]
    assert gate["passed"] is False
    assert gate["mismatched_ids"] == ["answerable", "refusal"]


def test_graded_group_with_unjudged_or_failed_question_has_no_comparable_main_score():
    from eval.run_record import summarize_results

    result = summarize_results([
        {"question_id": "judged", "run_status": "success", "graded": {
            "ranking_comparable": True, "score_status": "scored", "recall_at_k": 1.0,
            "recall_completion_at_k": 1.0, "mrr_at_k": 1.0, "ndcg_at_k": 1.0}},
        {"question_id": "unknown", "run_status": "success", "graded": {
            "ranking_comparable": False, "score_status": "unjudged_candidates", "recall_at_k": None}},
        {"question_id": "unlabeled", "run_status": "success", "graded": None},
        {"question_id": "failed", "run_status": "error", "graded": None},
    ])["graded_retrieval"]
    assert result["ranking_comparable"] is False
    assert result["counts"] == {"judged": 1, "unjudged": 1, "no_qrels": 1, "failed": 1, "skipped": 0}
    assert result["recall_at_k"]["value"] is None
    assert result["judged_subset_diagnostic"]["recall_at_k"] == {"value": 1.0, "denominator": 1}


def test_fully_judged_group_remains_comparable():
    from eval.run_record import summarize_results

    result = summarize_results([
        {"question_id": "q", "run_status": "success", "graded": {
            "ranking_comparable": True, "score_status": "scored", "recall_at_k": .5,
            "recall_completion_at_k": .5, "mrr_at_k": 1.0, "ndcg_at_k": .6}},
    ])["graded_retrieval"]
    assert result["ranking_comparable"] is True
    assert result["recall_at_k"] == {"value": .5, "denominator": 1}


def test_historical_identity_arm_is_isolated_from_current_safety(tmp_path, monkeypatch):
    from dataclasses import replace
    from evidence_assistant.config import settings
    from evidence_assistant.pipeline import EvidencePipeline
    from evidence_assistant.schemas import Entry, QuerySpec
    from eval.offline_runner import _pipeline

    monkeypatch.setenv('CEA_ISOLATED_WORKER', '1')
    cfg = replace(settings, cache_dir=tmp_path/'cache', enable_live_apis=False, enable_supabase=False, llm_api_key='')
    rows = [Entry(id=str(n), doc_id=f'unknown:{n}', source='pubmed_snapshot', title='Study',
                  text='Evidence', evidence_level='RCT', topic='高血压', score=.9) for n in range(3)]
    spec = QuerySpec(original='高血压研究', pico=None, api_queries=[], local_terms=[], domains=['高血压'])
    # Frozen legacy counted arbitrary doc IDs; current safety must reject them.
    assert not _pipeline(cfg, 'B1')._assess_top8_evidence(spec, rows).refused
    assert _pipeline(cfg, 'I1')._assess_top8_evidence(spec, rows).refused
    assert not _pipeline(cfg, 'I1')._assess_generation_evidence(spec, rows).refused
    assert _pipeline(cfg, 'G1')._assess_generation_evidence(spec, rows).refused
    assert EvidencePipeline(cfg)._assess_top8_evidence(spec, rows).refused
    monkeypatch.delenv('CEA_ISOLATED_WORKER')
    with pytest.raises(RuntimeError, match='isolated'):
        _pipeline(cfg, 'B1')


def test_identity_diagnostic_arm_uses_candidate_policy_only(tmp_path):
    from eval.offline_runner import settings_values
    cfg = settings_values(tmp_path, 'C0', 'I1', tmp_path/'cache')
    assert cfg['candidate_pool_policy'] == 'source_preserving'
    assert cfg['top8_selection_policy'] == 'legacy'


def test_current_c0_freeze_has_verifiable_inputs_without_history(tmp_path, monkeypatch):
    from eval import run_p0

    freeze = getattr(run_p0, 'freeze_current_baseline', None)
    assert callable(freeze), 'current C0 freeze API is missing'
    monkeypatch.setenv('LLM_API_KEY', 'SYNTHETIC-SECRET-NOT-FROZEN')
    output = tmp_path / 'current'
    info = freeze(output)
    assert info['source_kind'] == 'current_c0'
    assert info['commit'] != run_p0.BASELINE_COMMIT
    assert len(json.loads((output / 'frozen/eval/test_set.json').read_text())) == 15
    loaded = run_p0.load_baseline_metadata(output, 'current')
    assert loaded['commit'] == info['commit']
    manifest = json.loads((output / 'input_manifest.json').read_text())
    assert all(run_p0.sha256(output / item['path']) == item['sha256'] for item in manifest)
    assert 'SYNTHETIC-SECRET-NOT-FROZEN' not in (output / 'settings.json').read_text()
    assert not (output / 'frozen/data/raw/pdf_collection.sqlite3').exists()
    with pytest.raises(FileExistsError):
        freeze(output)


def test_current_c0_cannot_impersonate_history_or_run_historical_arms(tmp_path):
    from eval import run_p0

    freeze = getattr(run_p0, 'freeze_current_baseline', None)
    assert callable(freeze), 'current C0 freeze API is missing'
    baseline = tmp_path / 'current'
    freeze(baseline)
    with pytest.raises(ValueError, match='historical'):
        run_p0.load_baseline_metadata(baseline, 'historical')
    with pytest.raises(SystemExit):
        run_p0.main(['--baseline-source', 'current', '--baseline', str(baseline),
                     '--output', str(tmp_path / 'run'), '--profiles', 'C0', '--arms', 'B1'])
    assert not (tmp_path / 'run').exists()


def test_current_c0_rejects_changed_input_and_wrong_source(tmp_path):
    from eval import run_p0

    freeze = getattr(run_p0, 'freeze_current_baseline', None)
    assert callable(freeze), 'current C0 freeze API is missing'
    baseline = tmp_path / 'current'
    freeze(baseline)
    (baseline / 'frozen/eval/test_set.json').write_text('[]')
    with pytest.raises(ValueError, match='hash'):
        run_p0.load_baseline_metadata(baseline, 'current')
    with pytest.raises(ValueError, match='manifest'):
        run_p0.load_baseline_metadata(tmp_path / 'missing', 'current')


def test_frozen_current_baseline_runs_two_network_denied_repeats(tmp_path):
    from eval import run_p0

    freeze = getattr(run_p0, 'freeze_current_baseline', None)
    assert callable(freeze), 'current C0 freeze API is missing'
    baseline, output = tmp_path / 'baseline', tmp_path / 'run'
    info = freeze(baseline)
    assert run_p0.main(['--baseline-source', 'current', '--baseline', str(baseline),
                       '--output', str(output), '--profiles', 'C0', '--arms', 'G1']) == 0
    manifest = json.loads((output / 'manifest.json').read_text())
    summary = json.loads((output / 'summary.json').read_text())
    assert manifest['baseline_commit'] == info['commit']
    assert manifest['baseline_source_kind'] == 'current_c0'
    assert summary['repeat_stability']['C0/G1']['stable']
    assert summary['configurations']['C0/G1']['status_counts']['success'] == 15
    assert summary['reference_configurations']['C0/G1']['status_counts']['success'] == 15
    assert summary['engineering_gates']['C0/G1']['answer_behavior']['passed']
    for path in output.glob('C0/G1/repeat_*/network_audit.json'):
        audit = json.loads(path.read_text())
        assert audit['selftest']['passed'] and audit['unexpected_network_attempts'] == 0


def test_shared_service_performance_measures_one_pipeline_with_answerable_requests(tmp_path):
    from eval.offline_runner import run_performance, load_dataset, settings_values, construct_settings
    from evidence_assistant.config import Settings

    root = Path(__file__).resolve().parents[1]
    values = settings_values(tmp_path, 'C0', 'G1', tmp_path / 'cache')
    values.update(knowledge_dir=root / 'data/knowledge_pages',
                  local_corpus_path=root / 'data/raw/local_corpus.json')
    cfg = construct_settings(Settings, values)
    result = run_performance(cfg, 'G1', load_dataset(root / 'eval/test_set.json'), 100,
                             shared_pipeline=True)
    for group in result['profiles']:
        assert group['pipeline_count'] == 1
        assert group['actual_answered_count'] == 100
        assert group['errors'] == 0
        assert group['timeouts'] is None
        assert group['queue']['p95_ms'] is not None


@pytest.mark.parametrize('failure', ['repeat', 'network', 'selftest', 'integrity', 'commands'])
def test_regression_acceptance_rejects_unstable_or_unisolated_runs(failure):
    from eval import run_p0

    accept = getattr(run_p0, 'regression_accepted', None)
    assert callable(accept), 'regression acceptance gate is missing'
    summary = {'failed_commands': [], 'repeat_stability': {'C0/G1': {'stable': True}},
               'artifact_integrity': {'frozen_unchanged': True, 'baseline_artifacts_unchanged': True},
               'network_audits': [{'selftest': {'passed': True}, 'unexpected_network_attempts': 0}]}
    assert accept(summary)
    if failure == 'repeat':
        summary['repeat_stability']['C0/G1']['stable'] = False
    elif failure == 'network':
        summary['network_audits'][0]['unexpected_network_attempts'] = 1
    elif failure == 'selftest':
        summary['network_audits'][0]['selftest']['passed'] = False
    elif failure == 'integrity':
        summary['artifact_integrity']['frozen_unchanged'] = False
    else:
        summary['failed_commands'] = [{'exit_code': 1}]
    assert not accept(summary)


def test_current_regression_rejects_stable_all_refusal_without_reference(tmp_path):
    from eval.run_p0 import build_summary, regression_accepted
    from eval.run_record import write_json

    row = {'question_id': 'answerable', 'run_status': 'success', 'answer_status': 'refused',
           'should_answer': True, 'legacy': {'refusal_correct': False}}
    for repeat in (1, 2):
        directory = tmp_path / 'C0/G1' / ('repeat_%s' % repeat)
        directory.mkdir(parents=True)
        (directory / 'results.jsonl').write_text(json.dumps(row) + '\n')
        write_json(directory / 'network_audit.json', {'selftest': {'passed': True},
                                                    'unexpected_network_attempts': 0})
    summary = build_summary(tmp_path, ['C0'], ['G1'], [],
                            {'frozen_unchanged': True, 'baseline_artifacts_unchanged': True})
    assert summary['repeat_stability']['C0/G1']['stable']
    assert not regression_accepted(summary)


@pytest.mark.parametrize('metric', ['recall_at_8', 'ndcg_at_8', 'key_point_coverage',
                                   'citation_accuracy', 'supported_claim_rate'])
def test_current_regression_rejects_quality_loss_against_frozen_reference(tmp_path, metric):
    from eval.run_p0 import build_summary, regression_accepted
    from eval.run_record import write_json

    baseline = {'question_id': 'answerable', 'run_status': 'success', 'answer_status': 'answered',
                'should_answer': True, 'legacy': {'refusal_correct': True,
                'recall_at_8': 1.0, 'ndcg_at_8': 1.0, 'key_point_coverage': 1.0,
                'citation_accuracy': 1.0, 'supported_claim_rate': 1.0}}
    candidate = json.loads(json.dumps(baseline))
    candidate['legacy'][metric] = 0.5
    for directory, row in [(tmp_path / 'reference/C0/G1/repeat_1', baseline),
                           (tmp_path / 'C0/G1/repeat_1', candidate),
                           (tmp_path / 'C0/G1/repeat_2', candidate)]:
        directory.mkdir(parents=True)
        (directory / 'results.jsonl').write_text(json.dumps(row) + '\n')
        write_json(directory / 'network_audit.json', {'selftest': {'passed': True},
                                                    'unexpected_network_attempts': 0})
    summary = build_summary(tmp_path, ['C0'], ['G1'], [],
                            {'frozen_unchanged': True, 'baseline_artifacts_unchanged': True})
    assert summary['repeat_stability']['C0/G1']['stable']
    assert not regression_accepted(summary)
