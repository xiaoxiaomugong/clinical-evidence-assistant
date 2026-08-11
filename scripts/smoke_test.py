#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from evidence_assistant.pipeline import EvidencePipeline


def main() -> None:
    pipeline = EvidencePipeline()
    answer = pipeline.run("降压药应早上服用还是睡前服用？")
    refusal = pipeline.run("宠物犬的高血压应该如何用药？")
    assert not answer.answer.refused
    assert answer.citation_check and answer.citation_check.valid
    assert refusal.answer.refused
    print(
        f"PASS pdf_docs={pipeline.pdf_corpus.size} answer_entries={len(answer.entries)} "
        f"checked={len(answer.citation_check.checked)}"
    )


if __name__ == "__main__":
    main()
