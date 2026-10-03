"""Freeze, isolate, repeat and optionally compare a pre-existing reference version."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

from eval.run_p0 import ROOT, clean_environment, create_run_directory, freeze_current_baseline, load_baseline_metadata, sha256
from eval.run_record import write_json
from eval.independent.assets import content_hash, require_valid
from eval.independent.fixtures import corpus_manifest_hash
from eval.independent.contracts import ensure_artifact_location


def product_hash(code):
    paths = sorted((code / 'src').rglob('*.py')) + [code / 'config.py']
    return content_hash([{'path': str(p.relative_to(code)), 'sha256': sha256(p)} for p in paths])


def _run_workers(snapshot, bundle_path, harness, output, repeats, system):
    bundle = json.loads(bundle_path.read_text())
    rows, audits, commands = [], [], []
    for repeat in range(1, repeats + 1):
        destination = output / ('repeat_%d' % repeat)
        cache = output / ('env_%d' % repeat)
        for directory in (cache / 'home', cache / 'tmp'):
            directory.mkdir(parents=True)
        command = [sys.executable, '-m', 'eval.independent.worker', '--snapshot', str(snapshot),
                   '--bundle', str(bundle_path), '--output', str(destination), '--repeat', str(repeat)]
        log = output / ('worker_%d.log' % repeat)
        with log.open('w') as handle:
            result = subprocess.run(command, cwd=harness, env=clean_environment(harness, cache, snapshot / 'code/current'),
                                    stdout=handle, stderr=subprocess.STDOUT)
        commands.append({'repeat': repeat, 'exit_code': result.returncode, 'log': log.name})
        if not (destination / 'rows.json').exists():
            rows.extend({'question_id': q['id'], 'repeat': repeat, 'status': 'error',
                         'error_code': 'worker_failed', 'output': None, 'output_hash': None,
                         'ranked_source_ids': [], 'ranking_complete_k': 0, 'evidence': []} for q in bundle['questions'])
        else:
            rows.extend(json.loads((destination / 'rows.json').read_text()))
        audit = destination / 'network_audit.json'
        audits.append(json.loads(audit.read_text()) if audit.exists() else
                      {'selftest': {'passed': False}, 'unexpected_network_attempts': None})
    signatures = {}
    for row in rows:
        signatures.setdefault(row['question_id'], []).append(content_hash({k: row.get(k) for k in
            ('status', 'output', 'ranked_source_ids', 'evidence', 'error_code')}))
    return {'schema_version': 'independent-run-v1', 'run_id': output.parent.name + '-' + output.name,
            'asset_kind': bundle['asset_kind'], 'dataset_hash': content_hash(bundle),
            'protocol_hash': content_hash(bundle['protocol']), 'rubric_version': bundle['protocol']['rubric_version'],
            'corpus_manifest_hash': bundle['corpus']['manifest_hash'], 'system': system,
            'expected_count': len(bundle['questions']) * repeats, 'repeats': repeats, 'rows': rows,
            'repeat_consistency': {'consistent': all(len(set(v)) == 1 and len(v) == repeats for v in signatures.values()),
                                   'independent_sample_size': len(bundle['questions'])},
            'network_audits': audits, 'commands': commands, 'unavailable': {'C1': 'not_executed', 'clinical_pilot': 'not_executed'}}


def run_dataset(bundle, output, reference=None, repeats=2, source_root=ROOT):
    if type(repeats) is not int or repeats < 1:
        raise ValueError('repeats must be a positive integer')
    source_root, output = Path(source_root).resolve(), Path(output).resolve()
    if output == source_root or output in source_root.parents or any(
        source_root / directory == output or source_root / directory in output.parents
        for directory in ('src', 'eval', 'scripts', 'data/knowledge_pages', 'data/raw')):
        raise ValueError('Output must not contain or be inside frozen source directories')
    ensure_artifact_location(bundle, output)
    ensure_artifact_location(bundle, output, repository=source_root)
    require_valid(bundle, corpus_manifest_hash(source_root))
    if bundle['corpus']['profile'] != 'C0':
        raise ValueError('Independent runner currently supports C0; C1 not executed')
    reference_info = None
    if reference is not None:
        reference = Path(reference).resolve()
        reference_info = load_baseline_metadata(reference, 'current')
        if reference == output or reference in output.parents or output in reference.parents:
            raise ValueError('Output and immutable reference must be separate')
    run = create_run_directory(output)
    snapshot = run / 'candidate_snapshot'
    metadata = freeze_current_baseline(snapshot, source_root)
    harness = snapshot / 'code/current'
    bundle_path = run / 'assets.json'
    write_json(bundle_path, bundle)
    system = {'commit': metadata['commit'], 'working_tree_dirty': metadata['working_tree_dirty'],
              'source_hash': product_hash(harness), 'snapshot_manifest_hash': metadata['input_manifest_sha256'],
              'harness_hash': content_hash([{'path': str(p.relative_to(harness)), 'sha256': sha256(p)}
                                            for p in sorted((harness / 'eval').rglob('*.py'))])}
    candidate = _run_workers(snapshot, bundle_path, harness, run / 'candidate', repeats, system)
    candidate['comparison'] = {'status': 'not_requested', 'reason': 'No independent reference provided'}
    if reference_info is not None:
        before_snapshot = run / 'reference_snapshot'
        # Copy frozen reference code, but use identical effective data and orchestration.
        shutil.copytree(reference / 'code/current', before_snapshot / 'code/current')
        shutil.copytree(snapshot / 'frozen', before_snapshot / 'frozen')
        before_system = {'commit': reference_info['commit'], 'source_hash': product_hash(before_snapshot / 'code/current'),
                         'snapshot_manifest_hash': reference_info['input_manifest_sha256'], 'harness_hash': system['harness_hash']}
        before = _run_workers(before_snapshot, bundle_path, harness, run / 'reference', repeats, before_system)
        before['comparison'] = {'status': 'reference'}
        load_baseline_metadata(reference, 'current')
        if product_hash(before_snapshot / 'code/current') != before_system['source_hash'] or corpus_manifest_hash(before_snapshot / 'frozen') != bundle['corpus']['manifest_hash']:
            raise ValueError('Frozen reference inputs changed during execution')
        before['input_integrity'] = {'frozen_unchanged': True, 'reference_unchanged': True}
        write_json(run / 'reference_run.json', before)
        semantic = lambda r: {(row['question_id'], row['repeat']): content_hash({k: row.get(k) for k in
                                  ('status', 'output', 'ranked_source_ids', 'evidence')}) for row in r['rows']}
        candidate['comparison'] = {'status': 'compared', 'reference_system': before_system,
                                  'reference_manifest_hash': reference_info['input_manifest_sha256'],
                                  'same_effective_data': True, 'same_protocol': True,
                                  'semantic_equal': semantic(candidate) == semantic(before),
                                  'cross_version': before_system['source_hash'] != system['source_hash']}
    load_baseline_metadata(snapshot, 'current')
    candidate['input_integrity'] = {'frozen_unchanged': True, 'reference_unchanged': True if reference else None}
    write_json(run / 'run.json', candidate)
    return candidate


def engineering_execution_ok(run):
    return bool(run['rows'] and all(row['status'] == 'success' for row in run['rows'])
                and run['repeat_consistency']['consistent']
                and run['input_integrity']['frozen_unchanged']
                and all(audit['selftest']['passed'] and audit['unexpected_network_attempts'] == 0
                        for audit in run['network_audits']))
