"""Shared runtime boundaries for independent protocol records and destinations."""
from pathlib import Path

from eval.run_p0 import ROOT

ANSWER_LIST_FIELDS = ('limitations', 'found', 'missing', 'next_steps')


def locate_excerpt(original, rendered):
    """Map whitespace-only retrieval rendering back to exact frozen text offsets."""
    if not isinstance(original, str) or not isinstance(rendered, str):
        return None
    positions = [index for index, char in enumerate(original) if not char.isspace()]
    normalized = ''.join(original[index] for index in positions)
    needle = ''.join(char for char in rendered if not char.isspace())
    start = normalized.find(needle) if needle else -1
    if start < 0:
        return None
    left, right = positions[start], positions[start + len(needle) - 1] + 1
    return original[left:right], left, right


def ensure_artifact_location(bundle, *paths, repository=ROOT):
    if bundle.get('asset_kind') != 'controlled_clinical':
        return
    root = Path(repository).resolve()
    for path in paths:
        if path is not None:
            destination = Path(path).resolve()
            if destination == root or root in destination.parents:
                raise ValueError('Controlled clinical artifacts must be outside the repository')


def validate_output(output):
    if not isinstance(output, dict) or not all(key in output for key in ('behavior', 'answer', 'refusal_code')):
        raise ValueError('Output requires behavior, answer and refusal_code')
    if output['behavior'] not in ('answer', 'qualified_answer', 'refuse'):
        raise ValueError('Output behavior is invalid')
    code = output['refusal_code']
    if code is not None and not isinstance(code, str):
        raise ValueError('Output refusal_code requires string or null')
    answer = output['answer']
    if isinstance(answer, str):
        texts = [answer]
    elif isinstance(answer, dict):
        for field in ANSWER_LIST_FIELDS:
            if field in answer and (not isinstance(answer[field], list) or any(not isinstance(item, str) for item in answer[field])):
                raise ValueError('Output boundary and next-step fields require string arrays')
        paragraphs = answer.get('paragraphs', [])
        if not isinstance(paragraphs, list):
            raise ValueError('Output paragraphs require a list')
        texts = []
        for paragraph in paragraphs:
            if not isinstance(paragraph, dict) or not isinstance(paragraph.get('text'), str) or not paragraph['text'].strip():
                raise ValueError('Output paragraph requires nonempty text')
            if not isinstance(paragraph.get('citation_ids'), list):
                raise ValueError('Output paragraph requires citation_ids list')
            for field in ('claim_type', 'certainty'):
                if field in paragraph and not isinstance(paragraph[field], str):
                    raise ValueError('Output claim type and certainty require text')
            texts.append(paragraph['text'])
        if output['behavior'] == 'refuse':
            reason = answer.get('refusal_reason')
            if reason is not None and not isinstance(reason, str):
                raise ValueError('Refusal reason must be text')
            texts.append(reason or '')
    else:
        raise ValueError('Output answer requires text or paragraph object')
    if not any(text.strip() for text in texts):
        raise ValueError('Successful output requires answer or refusal reason')
    if output['behavior'] == 'refuse' and not (isinstance(code, str) and code.strip()):
        raise ValueError('Refusal output requires a refusal code')
