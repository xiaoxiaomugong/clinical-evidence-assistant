#!/usr/bin/env python3
"""Lint knowledge-page schema, traceability fields, and update metadata."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_PAGE_FIELDS = {"id", "title", "topic", "summary", "claims", "limitations", "updated_at"}
REQUIRED_CLAIM_FIELDS = {"id", "text", "evidence_level", "applicable", "exceptions", "citations"}


def lint(directory: Path) -> list:
    issues = []
    page_ids = set()
    claim_ids = set()
    for path in sorted(directory.glob("*.json")):
        try:
            page = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            issues.append({"file": path.name, "level": "error", "message": f"无法解析 JSON：{error}"})
            continue

        missing_page = sorted(REQUIRED_PAGE_FIELDS - set(page))
        if missing_page:
            issues.append({"file": path.name, "level": "error", "message": f"页面缺字段：{missing_page}"})
        page_id = str(page.get("id", ""))
        if not page_id or page_id in page_ids:
            issues.append({"file": path.name, "level": "error", "message": "页面 id 为空或重复"})
        page_ids.add(page_id)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(page.get("updated_at", ""))):
            issues.append({"file": path.name, "level": "warning", "message": "updated_at 不是 YYYY-MM-DD"})

        claims = page.get("claims", [])
        if not claims:
            issues.append({"file": path.name, "level": "error", "message": "主题页没有 claim"})
        for index, claim in enumerate(claims):
            location = f"{path.name}#claim-{index + 1}"
            missing_claim = sorted(REQUIRED_CLAIM_FIELDS - set(claim))
            if missing_claim:
                issues.append({"file": location, "level": "error", "message": f"claim 缺字段：{missing_claim}"})
            claim_id = str(claim.get("id", ""))
            if not claim_id or claim_id in claim_ids:
                issues.append({"file": location, "level": "error", "message": "claim id 为空或重复"})
            claim_ids.add(claim_id)
            citations = claim.get("citations", [])
            if not citations:
                issues.append({"file": location, "level": "error", "message": "claim 没有来源"})
            for citation in citations:
                citation_type = citation.get("type")
                url = str(citation.get("url", ""))
                if citation_type == "pmid" and not re.fullmatch(r"\d{5,9}", str(citation.get("pmid", ""))):
                    issues.append({"file": location, "level": "error", "message": "PMID 格式无效"})
                if citation_type == "pmid" and not citation.get("verified_at"):
                    issues.append({"file": location, "level": "warning", "message": "PMID 缺 verified_at"})
                parsed = urlparse(url)
                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    issues.append({"file": location, "level": "error", "message": "来源 URL 无效"})
    return issues


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT / "data" / "knowledge_pages")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    issues = lint(args.directory)
    print(json.dumps({"issues": issues, "count": len(issues)}, ensure_ascii=False, indent=2))
    if args.strict and any(issue["level"] == "error" for issue in issues):
        sys.exit(1)


if __name__ == "__main__":
    main()
