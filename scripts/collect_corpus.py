#!/usr/bin/env python3
"""Collect a reproducible multi-source snapshot without changing the bundled demo corpus."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from config import settings
from evidence_assistant.query_rewrite import rewrite
from evidence_assistant.retrievers import clinicaltrials_search, europepmc_search, pubmed_search


SEED_QUESTIONS = [
    "adult hypertension pharmacological treatment guideline",
    "dyslipidemia statin cardiovascular prevention guideline",
    "type 2 diabetes GLP-1 SGLT2 guideline",
    "stroke secondary prevention antiplatelet guideline",
    "Mediterranean diet sodium cardiovascular randomized trial",
]


def collect(target: int) -> list:
    per_call = max(5, min(40, (target // (len(SEED_QUESTIONS) * 3)) + 2))
    by_id = {}
    for question in SEED_QUESTIONS:
        spec = rewrite(question)
        # English seed strings are within scope semantically, but rule detection is Chinese-first.
        spec.out_of_scope = False
        spec.api_queries = [f"({question}) AND (guideline OR trial OR meta-analysis)"]
        for retriever in (pubmed_search, europepmc_search, clinicaltrials_search):
            try:
                documents = retriever(spec, top_k=per_call, cfg=settings)
            except Exception as error:  # collector reports individual source failures and continues
                print(f"WARN {retriever.__name__}: {type(error).__name__}: {error}", file=sys.stderr)
                continue
            for document in documents:
                if document.abstract and document.id not in by_id:
                    by_id[document.id] = document
            print(f"{retriever.__name__}: total unique={len(by_id)}")
            if len(by_id) >= target:
                return list(by_id.values())[:target]
    return list(by_id.values())


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect PubMed/Europe PMC/ClinicalTrials snapshot")
    parser.add_argument("--target", type=int, default=200)
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "raw" / "collected_snapshot.json")
    args = parser.parse_args()
    documents = collect(args.target)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        json.dump([asdict(document) for document in documents], handle, ensure_ascii=False, indent=2)
    print(f"Saved {len(documents)} unique records to {args.output}")


if __name__ == "__main__":
    main()
