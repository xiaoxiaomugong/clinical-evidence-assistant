import copy
import json
from pathlib import Path

import pytest


def test_clean_c0_runs_without_history_or_c1_and_requires_human_review(tmp_path):
    from eval.independent.fixtures import synthetic_bundle
    from eval.independent.runner import run_dataset
    from eval.independent.scoring import build_report

    bundle = synthetic_bundle()
    run = run_dataset(bundle, tmp_path / 'run')
    assert run['expected_count'] == len(bundle['questions']) * 2
    assert len(run['rows']) == run['expected_count']
    assert all(row['status'] == 'success' for row in run['rows'])
    assert all('next_steps' in row['output']['answer'] and 'limitations' in row['output']['answer'] for row in run['rows'])
    assert run['repeat_consistency']['consistent'] is True
    assert run['unavailable']['C1'] == 'not_executed'
    assert all(a['selftest']['passed'] and a['unexpected_network_attempts'] == 0 for a in run['network_audits'])
    assert run['comparison']['status'] == 'not_requested'
    assert build_report(bundle, run)['quality_decision'] != 'pass'
    with pytest.raises(FileExistsError):
        run_dataset(bundle, tmp_path / 'run')


def test_corpus_mismatch_and_missing_reference_fail_before_execution(tmp_path):
    from eval.independent.fixtures import synthetic_bundle
    from eval.independent.runner import run_dataset

    bundle = synthetic_bundle()
    bundle['corpus']['manifest_hash'] = '0' * 64
    with pytest.raises(ValueError, match='[Hh]ash|corpus'):
        run_dataset(bundle, tmp_path / 'wrong')
    assert not (tmp_path / 'wrong').exists()
    with pytest.raises(ValueError, match='manifest'):
        run_dataset(synthetic_bundle(), tmp_path / 'missing', reference=tmp_path / 'absent')


def test_runner_refuses_snapshot_recursion_and_controlled_data_in_repository(tmp_path):
    from eval.independent.fixtures import synthetic_bundle
    from eval.independent.runner import run_dataset
    from eval.run_p0 import ROOT

    with pytest.raises(ValueError, match='source directories'):
        run_dataset(synthetic_bundle(), ROOT / 'eval/unsafe-output')
    controlled = synthetic_bundle()
    controlled['asset_kind'] = 'controlled_clinical'
    with pytest.raises(ValueError, match='outside'):
        run_dataset(controlled, ROOT / 'data/eval_runs/private-would-be-unsafe')


def test_cross_version_reference_records_fixed_identity_and_same_effective_inputs(tmp_path):
    from eval.independent.fixtures import synthetic_bundle
    from eval.independent.runner import run_dataset
    from eval.run_p0 import freeze_current_baseline

    reference = tmp_path / 'reference'
    freeze_current_baseline(reference)
    run = run_dataset(synthetic_bundle(), tmp_path / 'run', reference=reference)
    assert run['comparison']['status'] == 'compared'
    assert run['comparison']['same_effective_data'] is True
    assert run['comparison']['reference_manifest_hash']
    assert run['comparison']['semantic_equal'] is True
    before = json.loads((tmp_path / 'run/reference_run.json').read_text())
    assert before['dataset_hash'] == run['dataset_hash']
    assert before['protocol_hash'] == run['protocol_hash']


def test_synthetic_two_arm_loop_uses_fixed_reference_and_question_pairing(tmp_path):
    from eval.independent.cli import synthetic_e2e
    from eval.run_p0 import freeze_current_baseline
    reference = tmp_path / 'reference'
    freeze_current_baseline(reference)
    summary = synthetic_e2e(tmp_path / 'e2e', reference=reference)
    report = json.loads((tmp_path / 'e2e/report.json').read_text())
    assert summary['engineering_complete'] is True
    assert report['comparison']['product_source_identical'] is True
    retrieval = report['comparison']['metrics']['retrieval.recall_at_8']
    assert retrieval['paired_questions'] == 2
    assert retrieval['interval']['n_observations'] == 2


def test_synthetic_e2e_exports_imports_adjudicates_without_clinical_pass(tmp_path):
    from eval.independent.cli import synthetic_e2e

    result = synthetic_e2e(tmp_path / 'e2e')
    assert result['scope'] == 'synthetic_engineering_acceptance'
    assert result['engineering_complete'] is True
    assert result['clinical_pilot'] == 'not_executed'
    assert result['unresolved_conflicts_before_adjudication'] >= 1
    assert result['unresolved_conflicts_after_adjudication'] == 0


def test_source_location_allows_only_whitespace_rendering_changes():
    from eval.independent.contracts import locate_excerpt
    assert locate_excerpt('First. Second.', 'First.  Second.') == ('First. Second.', 0, 14)
    assert locate_excerpt('First. Second.', 'First. Third.') is None


@pytest.mark.parametrize('command', ['import', 'report', 'validate'])
def test_controlled_cli_rejects_repository_outputs_before_reading_reviews(tmp_path, command):
    from eval.independent.cli import main
    from eval.independent.fixtures import synthetic_bundle
    from eval.run_p0 import ROOT
    bundle = synthetic_bundle()
    bundle['asset_kind'] = 'controlled_clinical'
    path = tmp_path / 'assets.json'
    path.write_text(json.dumps(bundle))
    args = [command, '--assets', str(path), '--output', str(ROOT / 'data/eval_runs/unsafe-controlled-output.json')]
    if command == 'import':
        args += ['--runs', str(tmp_path / 'missing.json'), '--mapping', str(tmp_path / 'missing.json'),
                 '--reviews', str(tmp_path / 'A.jsonl'), str(tmp_path / 'B.jsonl')]
    if command == 'report':
        args += ['--run', str(tmp_path / 'missing.json')]
    assert main(args) == 2
    assert not (ROOT / 'data/eval_runs/unsafe-controlled-output.json').exists()
