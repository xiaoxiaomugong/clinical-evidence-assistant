"""Clinical Evidence Assistant core package."""

from .pipeline import EvidencePipeline
from .tool import ClinicalEvidenceTool, query_clinical_evidence

__all__ = ["ClinicalEvidenceTool", "EvidencePipeline", "query_clinical_evidence"]
__version__ = "0.1.0"
