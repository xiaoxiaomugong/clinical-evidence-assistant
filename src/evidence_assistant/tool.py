from __future__ import annotations

from threading import Lock
from typing import Any, Dict, Optional

from .config import Settings, settings
from .pipeline import EvidencePipeline
from .query_service import MAX_QUESTION_LENGTH, QueryService, validate_mode, validate_question


TOOL_SCHEMA_VERSION = "1.0"
DISCLAIMER = (
    "仅供教学与研究，不构成诊断或治疗建议；请勿提交可识别患者身份的信息。"
)


class ClinicalEvidenceTool:
    """Thread-safe, framework-neutral adapter around the evidence pipeline."""

    def __init__(
        self,
        cfg: Settings = settings,
        pipeline: Optional[EvidencePipeline] = None,
    ) -> None:
        self._pipeline = pipeline or EvidencePipeline(cfg)
        self._service = QueryService(self._pipeline)

    def query(
        self,
        question: str,
        mode: str = "hybrid",
        enable_live_apis: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Return the complete, JSON-serializable evidence pipeline result."""
        result = self._service.run(question, mode=mode, enable_live_apis=enable_live_apis)

        payload = result.to_dict()
        payload["schema_version"] = TOOL_SCHEMA_VERSION
        payload["status"] = "refused" if result.answer.refused else "answered"
        payload["disclaimer"] = DISCLAIMER
        return payload


def _validate_question(question: str) -> str:
    return validate_question(question)


def _validate_mode(mode: str) -> str:
    return validate_mode(mode)


_default_tool: Optional[ClinicalEvidenceTool] = None
_default_tool_lock = Lock()


def get_default_tool() -> ClinicalEvidenceTool:
    global _default_tool
    if _default_tool is None:
        with _default_tool_lock:
            if _default_tool is None:
                _default_tool = ClinicalEvidenceTool()
    return _default_tool


def query_clinical_evidence(
    question: str,
    mode: str = "hybrid",
    enable_live_apis: Optional[bool] = None,
) -> Dict[str, Any]:
    """Query traceable clinical evidence for use by an agent or Python caller.

    Args:
        question: A de-identified clinical learning or research question.
        mode: Retrieval strategy: ``hybrid``, ``knowledge``, or ``rag``.
        enable_live_apis: Override live PubMed/Europe PMC/ClinicalTrials.gov use.
            Leave as ``None`` to use the configured default.
    """
    return get_default_tool().query(question, mode, enable_live_apis)


__all__ = [
    "ClinicalEvidenceTool",
    "DISCLAIMER",
    "TOOL_SCHEMA_VERSION",
    "get_default_tool",
    "query_clinical_evidence",
]
