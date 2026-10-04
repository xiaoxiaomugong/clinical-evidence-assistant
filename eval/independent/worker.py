"""Independent protocol worker; no legacy question-specific scoring or gates."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from eval.offline_runner import construct_settings, install_network_guard, network_selftest, settings_values
from eval.run_record import RunRecorder, write_json
from eval.independent.assets import content_hash
from eval.independent.contracts import locate_excerpt, validate_output


def execute(snapshot, bundle, output, repeat):
    # Settings import occurs only after environment isolation and audit installation.
    events = install_network_guard()
    selftest = network_selftest(events)
    if not selftest['passed']:
        raise RuntimeError('Network isolation selftest failed')
    from evidence_assistant.config import Settings
    from evidence_assistant.pipeline import EvidencePipeline
    cache = output / 'cache'
    values = settings_values(snapshot, 'C0', 'G1', cache)
    cfg = construct_settings(Settings, values, historical=True)
    write_json(output / 'settings.json', {k: v for k, v in values.items() if not k.endswith('key')})
    recorder = RunRecorder(output / 'records', 'C0', 'independent', repeat)
    pipeline = EvidencePipeline(cfg, recorder=recorder)
    sources = {s['id']: s for s in bundle['sources']}
    rows = []
    for question in bundle['questions']:
        recorder.start_question(question['id'])
        started = time.perf_counter()
        row = {'question_id': question['id'], 'repeat': repeat}
        try:
            result = pipeline.run(question['question'], mode='hybrid', enable_live_apis=False)
            answer = {'behavior': 'refuse' if result.answer.refused else 'answer',
                      'behavior_assessment': 'requires_independent_review',
                      'answer': {'paragraphs': [{'text': p.text, 'citation_ids': p.citation_ids,
                                                'claim_type': p.claim_type, 'certainty': p.certainty} for p in result.answer.paragraphs],
                                 'refusal_reason': result.answer.reason if result.answer.refused else '',
                                 'limitations': result.answer.limitations, 'found': result.answer.found,
                                 'missing': result.answer.missing, 'next_steps': result.answer.next_steps},
                      'refusal_code': result.answer.refusal_code}
            validate_output(answer)
            evidence = []
            for entry in result.entries:
                source = sources.get(entry.doc_id)
                located = locate_excerpt(source['text'], entry.text) if source else None
                evidence.append({'source_id': entry.doc_id, 'text': located[0] if located else entry.text,
                                 'retrieved_text': entry.text,
                                 'locator': dict(source['locator'], entry_id=entry.id, start=located[1],
                                                 end=located[2], quote=located[0]) if located else {},
                                 'citation_number': entry.citation_number})
            row.update(status='success', output=answer, output_hash=content_hash(answer),
                       ranked_source_ids=[e.doc_id for e in result.entries], ranking_complete_k=8,
                       evidence=evidence)
        except Exception as error:
            row.update(status='error', error_code=type(error).__name__, output=None, output_hash=None,
                       ranked_source_ids=[], ranking_complete_k=0, evidence=[])
        row['elapsed_ms'] = (time.perf_counter() - started) * 1000
        recorder.finish_question()
        rows.append(row)
    write_json(output / 'rows.json', rows)
    write_json(output / 'network_audit.json', {'selftest': selftest, 'events': list(events),
               'unexpected_network_attempts': sum(e['phase'] != 'selftest' for e in events)})
    return 0 if all(r['status'] == 'success' for r in rows) else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeat', type=int, required=True)
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=False)
    return execute(args.snapshot, json.loads(args.bundle.read_text()), args.output, args.repeat)


if __name__ == '__main__':
    raise SystemExit(main())
