"""Opt-in synchronous observations; no storage or raw data in public results."""
from __future__ import annotations

import copy
import time
from contextlib import contextmanager
from dataclasses import asdict


STAGES = ("rewrite_safety", "knowledge_retrieval", "snapshot_retrieval", "pdf_retrieval",
          "cloud_retrieval", "static_selection", "preliminary_pool", "preliminary_rerank",
          "live_retrieval", "pool", "rerank", "top8_selection", "evidence_gate",
          "generation_selection", "generation_gate", "generate", "verify", "sanitize", "post_gate")


class RunObserver:
    def __init__(self, recorder=None):
        self.recorder = recorder
        self.capture_content = recorder is not None and getattr(recorder, "capture_content", True)
        self.completed = set()
        self._claim_ids = []

    def emit(self, event, **payload):
        if self.recorder is not None and (self.capture_content or event in {"timing", "error"}):
            self.recorder(event, copy.deepcopy(payload))

    @contextmanager
    def measure(self, stage):
        started = time.perf_counter()
        status = "success"
        try:
            yield
        except Exception:
            status = "error"
            raise
        finally:
            self.completed.add(stage)
            self.emit("timing", stage=stage, status=status, elapsed_ms=(time.perf_counter()-started)*1000)

    def call(self, stage, function, *args, **kwargs):
        with self.measure(stage):
            return function(*args, **kwargs)

    def candidates(self, stage, entries, **details):
        if self.capture_content:
            self.emit("candidates", stage=stage, entries=[asdict(e) for e in entries], **details)

    def answer(self, stage, answer, claim_ids=None, **details):
        if self.capture_content:
            if claim_ids is not None:
                self._claim_ids = list(claim_ids)
            ids = [] if answer.refused else list(self._claim_ids)
            self.emit("answer", stage=stage, answer=asdict(answer), claim_ids=ids, **details)

    def finish(self):
        for stage in STAGES:
            if stage not in self.completed:
                self.emit("timing", stage=stage, status="not_run", elapsed_ms=None)
