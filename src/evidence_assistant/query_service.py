"""Validated, bounded, single-process access to a shared evidence pipeline."""
from __future__ import annotations

import math
import time
import weakref
from numbers import Real
from threading import Condition, Lock
from uuid import uuid4

from .pipeline import MODE_LABELS
from .runtime_logging import RuntimeRecorder


MAX_QUESTION_LENGTH = 4000


class QueryValidationError(ValueError):
    def __init__(self, message, request_id):
        super().__init__(message)
        self.request_id = request_id
        self.error_code = "invalid_input"


class QueryBusyError(RuntimeError):
    def __init__(self, request_id, error_code="queue_timeout"):
        super().__init__("服务繁忙，请稍后重试。")
        self.request_id = request_id
        self.error_code = error_code


class QueryExecutionError(RuntimeError):
    def __init__(self, request_id):
        super().__init__("本次请求处理失败，请稍后重试。")
        self.request_id = request_id
        self.error_code = "pipeline_error"


def validate_question(question):
    if not isinstance(question, str):
        raise ValueError("question 必须是字符串。")
    clean = question.strip()
    if not clean:
        raise ValueError("question 不能为空。")
    if len(clean) > MAX_QUESTION_LENGTH:
        raise ValueError(f"question 不能超过 {MAX_QUESTION_LENGTH} 个字符。")
    return clean


def validate_mode(mode):
    if not isinstance(mode, str) or mode not in MODE_LABELS:
        raise ValueError("不支持的 mode；可选值：hybrid、knowledge、rag。")
    return MODE_LABELS[mode]


class _PipelineGuard:
    def __init__(self):
        self.condition = Condition()
        self.active = False
        self.waiters = 0

    def acquire(self, request_id, max_wait_seconds, max_waiters):
        deadline = time.monotonic() + max_wait_seconds
        with self.condition:
            if self.active:
                if self.waiters >= max_waiters:
                    raise QueryBusyError(request_id, "queue_full")
                self.waiters += 1
                try:
                    while self.active:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise QueryBusyError(request_id)
                        self.condition.wait(remaining)
                    # Waking after release does not grant extra queue budget.
                    # The condition lock may only be reacquired after expiry.
                    if time.monotonic() >= deadline:
                        raise QueryBusyError(request_id)
                finally:
                    self.waiters -= 1
            self.active = True

    def release(self):
        with self.condition:
            self.active = False
            self.condition.notify_all()


_guards = weakref.WeakKeyDictionary()
_guards_lock = Lock()


def _guard_for(pipeline):
    with _guards_lock:
        guard = _guards.get(pipeline)
        if guard is None:
            guard = _PipelineGuard()
            _guards[pipeline] = guard
        return guard


class QueryService:
    def __init__(self, pipeline, *, max_wait_seconds=5.0, max_waiters=8):
        if (not isinstance(max_wait_seconds, Real) or isinstance(max_wait_seconds, bool)
                or not math.isfinite(max_wait_seconds) or not 0 <= max_wait_seconds <= 60):
            raise ValueError("max_wait_seconds 必须在 0 到 60 秒之间。")
        if not isinstance(max_waiters, int) or isinstance(max_waiters, bool) or not 0 <= max_waiters <= 128:
            raise ValueError("max_waiters 必须是 0 到 128 之间的整数。")
        self.pipeline = pipeline
        self.max_wait_seconds = float(max_wait_seconds)
        self.max_waiters = max_waiters
        self._guard = _guard_for(pipeline)

    def run(self, question, mode="hybrid", enable_live_apis=None):
        request_id = str(uuid4())
        try:
            clean_question = validate_question(question)
            clean_mode = validate_mode(mode)
            if enable_live_apis is not None and not isinstance(enable_live_apis, bool):
                raise ValueError("enable_live_apis 必须是 true、false 或 null。")
        except ValueError as error:
            recorder = RuntimeRecorder(request_id, mode)
            recorder.finish("invalid_input", queue_elapsed_ms=0, execution_elapsed_ms=0, error_code="invalid_input")
            raise QueryValidationError(str(error), request_id) from None

        recorder = RuntimeRecorder(request_id, clean_mode,
                                   corpus_version=getattr(getattr(self.pipeline, "settings", None), "corpus_version", "unknown"))
        queued = time.perf_counter()
        try:
            self._guard.acquire(request_id, self.max_wait_seconds, self.max_waiters)
        except QueryBusyError as error:
            recorder.finish("busy", queue_elapsed_ms=(time.perf_counter() - queued) * 1000,
                            execution_elapsed_ms=0, error_code=error.error_code)
            raise

        queue_elapsed_ms = (time.perf_counter() - queued) * 1000
        started = time.perf_counter()
        try:
            result = self.pipeline.run(clean_question, mode=clean_mode,
                                       enable_live_apis=enable_live_apis, recorder=recorder)
            result.request_id = request_id
            result.queue_elapsed_ms = round(queue_elapsed_ms, 3)
            result.execution_elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
            recorder.finish("refused" if result.answer.refused else "answered",
                            queue_elapsed_ms=result.queue_elapsed_ms,
                            execution_elapsed_ms=result.execution_elapsed_ms, result=result)
            return result
        except Exception:
            recorder.finish("error", queue_elapsed_ms=queue_elapsed_ms,
                            execution_elapsed_ms=(time.perf_counter() - started) * 1000, error_code="pipeline_error")
            raise QueryExecutionError(request_id) from None
        finally:
            self._guard.release()
