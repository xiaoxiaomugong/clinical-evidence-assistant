#!/usr/bin/env python3
"""Verify all knowledge-page PMID references against NCBI E-utilities."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]


def load_pmids() -> dict:
    expected = {}
    for path in sorted((ROOT / "data" / "knowledge_pages").glob("*.json")):
        with path.open("r", encoding="utf-8") as handle:
            page = json.load(handle)
        for claim in page.get("claims", []):
            for citation in claim.get("citations", []):
                if citation.get("type") == "pmid" and citation.get("pmid"):
                    expected[citation["pmid"]] = citation.get("source", "")
    return expected


def verify(pmids: dict, timeout: int = 15) -> dict:
    response = requests.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
        params={"db": "pubmed", "id": ",".join(sorted(pmids)), "retmode": "json"},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json().get("result", {})
    return {
        pmid: {
            "exists": pmid in payload and "error" not in payload.get(pmid, {}),
            "expected_source": source,
            "title": payload.get(pmid, {}).get("title", ""),
            "year": payload.get(pmid, {}).get("pubdate", ""),
        }
        for pmid, source in pmids.items()
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true", help="Return nonzero when any PMID is missing")
    args = parser.parse_args()
    result = verify(load_pmids())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.strict and not all(item["exists"] for item in result.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
