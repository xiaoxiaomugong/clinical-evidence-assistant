"""Versioned independent evaluation CLI. Synthetic acceptance is not a clinical pilot."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from eval.independent.assets import content_hash, load_bundle, validate_bundle
from eval.independent.fixtures import synthetic_bundle
from eval.independent.contracts import ensure_artifact_location
from eval.independent.runner import engineering_execution_ok, run_dataset
from eval.run_p0 import create_run_directory
from eval.run_record import write_json


def read_json(path):
    return load_bundle(path)


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write('\n')


def synthetic_e2e(output, reference=None):
    from eval.independent.blind import export_blind, import_reviews
    from eval.independent.scoring import build_report
    root = create_run_directory(Path(output))
    bundle = synthetic_bundle()
    write_json(root / 'synthetic_assets.json', bundle)
    validation = validate_bundle(bundle)
    write_json(root / 'validation.json', validation)
    run = run_dataset(bundle, root / 'c0', reference=reference)
    before = read_json(root / 'c0/reference_run.json') if reference else None
    runs = [run, before] if before else [run]
    exported = export_blind(bundle, runs, root / 'reviewers', root / 'owner', seed=17)
    template = [json.loads(line) for line in Path(exported['review_template']).read_text().splitlines() if line.strip()]
    package = read_json(exported['public_package'])
    public_items = {item['item_id']: item for item in package['items']}
    reviews_a, reviews_b = [], []
    questions = {q['id']: q for q in bundle['questions']}
    for blank in template:
        item = copy.deepcopy(blank)
        item['reviewer_id'] = 'synthetic-reviewer-A'
        evidence = public_items[item['item_id']]['evidence']
        item['source_ids'] = [entry['source_id'] for entry in evidence]
        item['evidence_locations'] = [{'source_id': entry['source_id'], 'locator': entry['locator']} for entry in evidence]
        item['labels'] = {'behavior': questions[item['question_id']]['expected_behavior'],
                          'support_rate': 1.0, 'key_point_coverage': 1.0, 'numeric_correctness': 1.0,
                          'refusal_quality': 1.0, 'serious_error': False, 'error_types': [],
                          'rationale': 'SYNTHETIC LABEL: workflow acceptance only, never clinical judgment'}
        reviews_a.append(item)
        second = copy.deepcopy(item)
        second['reviewer_id'] = 'synthetic-reviewer-B'
        reviews_b.append(second)
    reviews_b[0]['labels']['support_rate'] = 0.5
    for name, rows in [('A', reviews_a), ('B', reviews_b)]:
        (root / ('synthetic_review_%s.jsonl' % name)).write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows))
    paths = [root / 'synthetic_review_A.jsonl', root / 'synthetic_review_B.jsonl']
    pending = import_reviews(bundle, runs, exported['private_mapping'], paths)
    write_json(root / 'pending_annotations.json', pending)
    # Independent synthetic adjudicator resolves the intentionally injected disagreement.
    arbitration = dict(reviews_a[0])
    arbitration['reviewer_id'] = 'synthetic-arbitrator'
    arbitration['adjudication_rationale'] = 'Synthetic arbitration exercises a disagreement; no clinical review occurred'
    write_json(root / 'synthetic_adjudication.json', [arbitration])
    annotations = import_reviews(bundle, runs, exported['private_mapping'], paths, root / 'synthetic_adjudication.json')
    write_json(root / 'annotations.json', annotations)
    report = build_report(bundle, run, annotations, before, annotations if before else None)
    write_json(root / 'report.json', report)
    summary = {'scope': 'synthetic_engineering_acceptance', 'clinical_pilot': 'not_executed',
               'engineering_complete': bool(validation['valid'] and all(engineering_execution_ok(r) for r in runs)
                 and not annotations['errors'] and not annotations['missing'] and not annotations['conflicts']
                 and len(annotations['final']) == sum(len(r['rows']) for r in runs)),
               'unresolved_conflicts_before_adjudication': len(pending['conflicts']),
               'unresolved_conflicts_after_adjudication': len(annotations['conflicts']),
               'C1': 'not_executed', 'report': 'report.json'}
    write_json(root / 'acceptance.json', summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    val = sub.add_parser('validate'); val.add_argument('--assets', required=True, type=Path)
    val.add_argument('--corpus-hash'); val.add_argument('--output', type=Path)
    run = sub.add_parser('run'); run.add_argument('--assets', required=True, type=Path)
    run.add_argument('--output', required=True, type=Path); run.add_argument('--reference', type=Path)
    run.add_argument('--repeats', type=int, default=2)
    export = sub.add_parser('export'); export.add_argument('--assets', required=True, type=Path)
    export.add_argument('--runs', required=True, nargs='+', type=Path)
    export.add_argument('--public-dir', required=True, type=Path); export.add_argument('--private-dir', required=True, type=Path)
    export.add_argument('--seed', type=int, default=0)
    imp = sub.add_parser('import'); imp.add_argument('--assets', required=True, type=Path)
    imp.add_argument('--runs', required=True, nargs='+', type=Path); imp.add_argument('--mapping', required=True, type=Path)
    imp.add_argument('--reviews', required=True, nargs=2, type=Path); imp.add_argument('--adjudications', type=Path)
    imp.add_argument('--output', required=True, type=Path)
    report = sub.add_parser('report'); report.add_argument('--assets', required=True, type=Path)
    report.add_argument('--run', required=True, type=Path); report.add_argument('--annotations', type=Path)
    report.add_argument('--baseline-run', type=Path); report.add_argument('--baseline-annotations', type=Path)
    report.add_argument('--output', required=True, type=Path)
    e2e = sub.add_parser('synthetic-e2e'); e2e.add_argument('--output', required=True, type=Path)
    e2e.add_argument('--reference', type=Path)
    fixture = sub.add_parser('synthetic-fixture'); fixture.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'synthetic-fixture':
            write_new(args.output, synthetic_bundle()); return 0
        if args.command == 'synthetic-e2e':
            result = synthetic_e2e(args.output, args.reference)
            print(json.dumps(result, ensure_ascii=False)); return 0 if result['engineering_complete'] else 1
        bundle = load_bundle(args.assets)
        ensure_artifact_location(bundle, getattr(args, 'output', None),
                                 getattr(args, 'public_dir', None), getattr(args, 'private_dir', None))
        if args.command == 'validate':
            result = validate_bundle(bundle, args.corpus_hash)
            if args.output: write_new(args.output, result)
            print(json.dumps(result, ensure_ascii=False)); return 0 if result['valid'] else 1
        if args.command == 'run':
            result = run_dataset(bundle, args.output, args.reference, args.repeats)
            print(str(args.output.resolve() / 'run.json'))
            return 0 if engineering_execution_ok(result) else 1
        if args.command == 'export':
            from eval.independent.blind import export_blind
            result = export_blind(bundle, [read_json(p) for p in args.runs], args.public_dir, args.private_dir, args.seed)
            print(json.dumps(result, default=str)); return 0
        if args.command == 'import':
            from eval.independent.blind import import_reviews
            result = import_reviews(bundle, [read_json(p) for p in args.runs], args.mapping, args.reviews, args.adjudications)
            write_new(args.output, result)
            return 0 if not any(result[k] for k in ('errors', 'missing', 'conflicts', 'unjudgeable')) else 1
        from eval.independent.scoring import build_report
        result = build_report(bundle, read_json(args.run), read_json(args.annotations) if args.annotations else None,
                              read_json(args.baseline_run) if args.baseline_run else None,
                              read_json(args.baseline_annotations) if args.baseline_annotations else None)
        write_new(args.output, result)
        print(str(args.output.resolve())); return 0
    except (ValueError, OSError, TypeError, KeyError) as error:
        # Deliberately avoid echoing data, credentials or raw parser exception text.
        print(json.dumps({'status': 'invalid', 'error_type': type(error).__name__,
                          'errors': getattr(error, 'errors', None)}))
        return 2
