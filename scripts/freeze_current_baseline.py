#!/usr/bin/env python3
"""Freeze current C0 code/data/questions/config into a new, verifiable directory."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from eval.run_p0 import freeze_current_baseline


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New directory; never overwritten')
    args = parser.parse_args(argv)
    freeze_current_baseline(args.output)
    print(args.output.resolve() / 'manifest.json')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
