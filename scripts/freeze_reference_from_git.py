#!/usr/bin/env python3
"""Freeze a fixed Git reference for regression; never fall back to current code."""
from __future__ import annotations

import argparse
import io
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from eval.run_p0 import freeze_current_baseline
from eval.run_record import write_json


def freeze_reference(repository, ref, output):
    repository, output = Path(repository).resolve(), Path(output).resolve()
    try:
        commit = subprocess.check_output(['git', 'rev-parse', '--verify', ref + '^{commit}'], cwd=repository,
                                         stderr=subprocess.DEVNULL, text=True).strip()
        archive = subprocess.check_output(['git', 'archive', commit, 'src', 'eval', 'scripts', 'data/knowledge_pages',
                                          'data/raw/local_corpus.json', 'data/corpus_version.json',
                                          'config.py', 'app.py', 'pyproject.toml', 'requirements.txt'], cwd=repository,
                                         stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        raise ValueError('Independent Git reference unavailable; no self-comparison fallback') from None
    with tempfile.TemporaryDirectory(prefix='cea-reference-') as temporary:
        source = Path(temporary)
        with tarfile.open(fileobj=io.BytesIO(archive)) as handle:
            for member in handle:
                path = Path(member.name)
                if path.is_absolute() or '..' in path.parts or member.issym() or member.islnk():
                    raise ValueError('Unsafe Git reference archive')
                if member.isfile():
                    destination = source / path
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(handle.extractfile(member).read())
        info = freeze_current_baseline(output, source)
    info.update(commit=commit, working_tree_dirty=False, reference_kind='git_archive', requested_ref=ref)
    write_json(output / 'manifest.json', info)
    return info


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    freeze_reference(ROOT, args.ref, args.output)
    print(str(args.output.resolve() / 'manifest.json'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
