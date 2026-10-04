"""Content-free request records for the server's standard stderr log stream."""
from __future__ import annotations

import json
import logging
import math
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from functools import lru_cache
from numbers import Real
from pathlib import Path
from uuid import UUID

from .observability import STAGES


LOGGER = logging.getLogger("evidence_assistant.runtime")
APP_VERSION = "0.1.0"
TIMING_STAGES = frozenset(STAGES) | {"full_pipeline", "queue"}
STATUSES = {"answered", "refused", "busy", "error", "invalid_input"}
ERROR_CODES = {"", "invalid_input", "queue_timeout", "queue_full", "pipeline_error"}
DEPENDENCY_STATUSES = {"disabled", "not_attempted", "success", "empty", "error", "fallback"}
DEPENDENCIES = {"pubmed", "europepmc", "clinicaltrials", "supabase", "generator"}
BACKENDS = {"not_run", "legacy", "dense", "hybrid", "deterministic", "cross_encoder",
            "extractive", "llm", "openai", "openai_compatible", "pubmed", "europepmc",
            "clinicaltrials", "supabase", "disabled", "unknown", ""}
REFUSAL_CODES = {"", "PHI_BLOCKED", "PERSONALIZED_TREATMENT", "OUT_OF_SCOPE",
                 "UNVERIFIABLE_INTERVENTION", "NO_EVIDENCE", "LOW_RELEVANCE",
                 "INSUFFICIENT_SOURCES", "MISSING_EVIDENCE_TYPE", "UNRESOLVED_CONFLICT",
                 "GENERATOR_REFUSAL", "NO_SUPPORTED_CLAIMS", "CITATION_FAILURE"}
REASON_CODES = {"not_started", "disabled", "not_configured", "offline_extractive", "success",
                "empty", "no_results", "request_error", "timeout", "http_error", "rate_limited",
                "invalid_json", "invalid_payload", "missing_fields", "configuration_error",
                "llm_error", "backend_unavailable", "retry_exhausted", "unknown", "",
                "safety_gate", "mode_excluded", "local_evidence_sufficient", "evidence_gate",
                "generation_gate", "completed", "connection_error", "invalid_response", "dependency_error"}
DEGRADATION_CODES = {"retrieval_backend_invalid", "retrieval_backend_unavailable",
                     "rerank_backend_invalid", "rerank_backend_unavailable"} | {
    f"{name}:{reason}" for name in DEPENDENCIES for reason in REASON_CODES if reason
}


def _duration(value):
    if isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
        return round(float(value), 3)
    return None


def _enum(value, allowed, default="unknown"):
    return value if isinstance(value, str) and value in allowed else default


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _version(value):
    return value if isinstance(value, str) and re.fullmatch(r"v?\d+(?:\.\d+){0,2}", value) else "unknown"


@lru_cache(maxsize=1)
def _build_revision():
    explicit = os.getenv("EVIDENCE_ASSISTANT_BUILD_SHA", "")
    if re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", explicit):
        return explicit.lower()
    package_root = Path(__file__).resolve().parents[2]
    if not (package_root / ".git").exists():
        return "unknown"
    try:
        completed = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=package_root,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   text=True, timeout=2, check=False)
        revision = completed.stdout.strip()
        if completed.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", revision):
            return revision
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


def _configure_logger():
    # A dedicated handler prevents an application's root stdout handler from
    # corrupting MCP stdio. Administrators may replace it with server handlers.
    if not LOGGER.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(message)s"))
        LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False


class RuntimeRecorder:
    """One recorder per request; only selected numeric and enum values survive."""

    capture_content = False

    def __init__(self, request_id: str, mode: str, *, corpus_version: str = "unknown"):
        self.request_id = str(UUID(request_id))
        self.mode = _enum(mode, {"hybrid", "knowledge", "rag"})
        self.corpus_version = _version(corpus_version)
        self.stage_timings = {}
        _configure_logger()

    def __call__(self, event, payload):
        if event != "timing" or not isinstance(payload, dict):
            return
        stage, status = payload.get("stage"), payload.get("status")
        if not isinstance(stage, str) or stage not in TIMING_STAGES:
            return
        if not isinstance(status, str) or status not in {"success", "error", "not_run"}:
            return
        elapsed = _duration(payload.get("elapsed_ms"))
        if elapsed is None and not (status == "not_run" and payload.get("elapsed_ms") is None):
            return
        self.stage_timings[stage] = {"status": status, "elapsed_ms": elapsed}

    def finish(self, status, *, queue_elapsed_ms, execution_elapsed_ms, result=None, error_code=""):
        record = {
            "schema_version": "1.0", "request_id": self.request_id,
            "timestamp": datetime.now(timezone.utc).isoformat(), "app_version": APP_VERSION,
            "build_revision": _build_revision(),
            "corpus_version": self.corpus_version, "mode": self.mode,
            "status": _enum(status, STATUSES), "error_code": _enum(error_code, ERROR_CODES),
            "queue_elapsed_ms": _duration(queue_elapsed_ms),
            "execution_elapsed_ms": _duration(execution_elapsed_ms),
            "stage_timings": self.stage_timings,
        }
        if result is not None:
            dependencies = self._dependencies(getattr(result, "dependency_states", {}))
            generator_state = dependencies.get("generator")
            generator_backend = _enum(result.answer.generator, BACKENDS)
            if generator_state is not None:
                generator_backend = ("not_run" if generator_state["status"] in {"disabled", "not_attempted"}
                                     else generator_state["actual_backend"] or "unknown")
            record.update({
                "retrieval_backend": _enum(result.retrieval_backend, BACKENDS),
                "rerank_backend": _enum(result.rerank_backend, BACKENDS),
                "generator_backend": generator_backend,
                "refusal_code": _enum(result.answer.refusal_code, REFUSAL_CODES),
                "degraded": bool(result.degraded), "entry_count": len(result.entries),
                "degradation_codes": [code for code in result.degradation_reasons
                                      if isinstance(code, str) and code in DEGRADATION_CODES],
                "checked_citation_count": len(result.citation_check.checked) if result.citation_check else 0,
                "generation_entry_count": len(result.generation_entry_ids),
                "dependency_states": dependencies,
            })
        # Logging failure must never replace a validated answer or block release.
        try:
            LOGGER.info(json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":")))
        except Exception:
            pass

    @staticmethod
    def _dependencies(states):
        output = {}
        if not isinstance(states, dict):
            return output
        for name, state in states.items():
            if name not in DEPENDENCIES:
                continue
            get = state.get if isinstance(state, dict) else lambda key, default=None: getattr(state, key, default)
            output[name] = {
                "status": _enum(get("status"), DEPENDENCY_STATUSES),
                "reason_code": _enum(get("reason_code"), REASON_CODES),
                "elapsed_ms": _duration(get("elapsed_ms")), "result_count": _count(get("result_count")),
                "actual_backend": _enum(get("actual_backend"), BACKENDS),
            }
        return output
