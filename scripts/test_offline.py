#!/usr/bin/env python3
"""Run regression tests with clean configuration and an external-network guard."""
from __future__ import annotations

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / "src"):
    sys.path.insert(0, str(directory))

from scripts.local_runtime import install_loopback_only_guard, prepare_offline_environment


def main() -> int:
    prepare_offline_environment(os.environ, ROOT)
    install_loopback_only_guard()
    import pytest

    os.chdir(ROOT)
    return pytest.main(sys.argv[1:] or ["-q"])


if __name__ == "__main__":
    raise SystemExit(main())
