"""Clinical Evidence Assistant core package.

The public objects are imported lazily so desktop launchers can configure data
and cache locations before the pipeline reads its environment.
"""

from __future__ import annotations

from typing import Any

__all__ = ["ClinicalEvidenceTool", "EvidencePipeline", "query_clinical_evidence"]
__version__ = "0.1.0"


def __getattr__(name: str) -> Any:
    if name == "EvidencePipeline":
        from .pipeline import EvidencePipeline

        return EvidencePipeline
    if name in {"ClinicalEvidenceTool", "query_clinical_evidence"}:
        from .tool import ClinicalEvidenceTool, query_clinical_evidence

        return {
            "ClinicalEvidenceTool": ClinicalEvidenceTool,
            "query_clinical_evidence": query_clinical_evidence,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
