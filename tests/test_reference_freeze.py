import json
from pathlib import Path

import pytest


def test_git_reference_freeze_is_fixed_and_captures_source_identity(tmp_path):
    from scripts.freeze_reference_from_git import freeze_reference
    from eval.run_p0 import ROOT, load_baseline_metadata
    info = freeze_reference(ROOT, 'HEAD', tmp_path / 'reference')
    assert info['reference_kind'] == 'git_archive'
    assert len(info['commit']) == 40
    assert info['requested_ref'] == 'HEAD'
    assert load_baseline_metadata(tmp_path / 'reference', 'current')['commit'] == info['commit']


def test_missing_reference_fails_without_self_comparison(tmp_path):
    from scripts.freeze_reference_from_git import freeze_reference
    from eval.run_p0 import ROOT
    with pytest.raises(ValueError, match='unavailable'):
        freeze_reference(ROOT, 'definitely-not-a-ref', tmp_path / 'reference')
    assert not (tmp_path / 'reference').exists()
