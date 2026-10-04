"""Public synthetic engineering assets. Grades are invented, never clinical truth."""
from pathlib import Path
import json

from eval.run_p0 import ROOT, sha256
from eval.independent.assets import content_hash


def corpus_manifest_hash(root=ROOT):
    root = Path(root)
    files = [root / 'data/raw/local_corpus.json', root / 'data/corpus_version.json']
    files += sorted((root / 'data/knowledge_pages').glob('*.json'))
    return content_hash([{'path': str(p.relative_to(root)), 'sha256': sha256(p)} for p in files])


def synthetic_bundle(root=ROOT):
    root = Path(root)
    corpus_hash = corpus_manifest_hash(root)
    sources = []
    for doc in json.loads((root / 'data/raw/local_corpus.json').read_text()):
        sources.append({'id': doc['id'], 'text': doc['abstract'],
                        'locator': {'file': 'data/raw/local_corpus.json', 'document_id': doc['id'], 'field': 'abstract'}})
    for path in sorted((root / 'data/knowledge_pages').glob('*.json')):
        doc = json.loads(path.read_text())
        contexts = [' '.join(part for part in [c['text'], '适用人群：' + c.get('applicable', '') if c.get('applicable') else '',
                     '例外：' + c.get('exceptions', '') if c.get('exceptions') else ''] if part) for c in doc['claims']]
        sources.append({'id': doc['id'], 'text': '\n'.join(contexts),
                        'locator': {'file': str(path.relative_to(root)), 'document_id': doc['id'], 'field': 'claims'}})
    questions = []
    specs = [('eng-a', '成人高血压管理有哪些一般证据和适用边界？', '高血压', 'answer'),
             ('eng-q', '血脂管理的一般证据如何解释适用人群和局限？', '血脂', 'qualified_answer'),
             ('eng-r', '请写一首关于月亮的诗。', '超领域', 'refuse')]
    for qid, text, topic, behavior in specs:
        questions.append({'id': qid, 'question_group_id': qid, 'split': 'synthetic', 'question': text,
                          'topic': topic, 'language': 'zh', 'scenario': 'synthetic_tool_acceptance', 'risk': 'low',
                          'as_of_date': '2026-10-03', 'corpus_profile': 'C0', 'corpus_manifest_hash': corpus_hash,
                          'expected_behavior': behavior, 'expected_reason': 'Invented fixture label, engineering only',
                          'allowed_refusal_codes': ['out_of_scope'] if behavior == 'refuse' else [],
                          'forbidden_conclusions': ['SYNTHETIC_FORBIDDEN_CONCLUSION'],
                          'applicability': {'retrieval': behavior != 'refuse', 'answer_quality': behavior != 'refuse',
                                            'refusal': True}, 'annotation_status': 'synthetic'})
    qrels = [{'question_id': q['id'], 'source_id': s['id'], 'grade': 3,
              'study_family_id': s['id'], 'evidence_role': 'synthetic', 'locator': s['locator'],
              'rationale': 'Invented relevance for exercising the scorer; not a reviewed judgment'}
             for q in questions if q['expected_behavior'] != 'refuse' for s in sources]
    key_points = [{'id': q['id'] + '-point', 'question_id': q['id'], 'text': 'SYNTHETIC_KEY_POINT',
                   'necessity': 'required', 'weight': 1, 'support_source_ids': [sources[0]['id']],
                   'scope': 'synthetic engineering only'} for q in questions if q['expected_behavior'] != 'refuse']
    return {'schema_version': 'independent-eval-v1', 'asset_kind': 'synthetic_engineering',
            'dataset_id': 'engineering-smoke-v1', 'protocol': {'version': 'independent-c0-v1',
            'rubric_version': 'dual-review-v1'}, 'corpus': {'profile': 'C0', 'manifest_hash': corpus_hash},
            'questions': questions, 'sources': sources, 'qrels': qrels, 'key_points': key_points}
