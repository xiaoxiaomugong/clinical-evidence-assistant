from pathlib import Path
from types import SimpleNamespace

import pytest

from evidence_assistant.schemas import Answer, AnswerParagraph, CitationCheck, DependencyState, PipelineResult


class WebPipeline:
    def __init__(self):
        self.knowledge = SimpleNamespace(page_count=5)
        self.local_corpus = SimpleNamespace(size=12)
        self.pdf_corpus = SimpleNamespace(stats=lambda: {"documents": 0, "full_text": 0})
        self.supabase_corpus = None
        self.supabase_configuration_error = "synthetic secret sk-config"
        self.calls = []
        self.outcome = "success"
        self.states = {}
        self.degraded = False

    def run(self, question, mode="hybrid", enable_live_apis=None, *, recorder=None):
        self.calls.append((question, mode, enable_live_apis))
        if self.outcome == "error":
            raise RuntimeError("姓名张三 病历号 A123456 sk-private https://private.invalid/input")
        answer = Answer(self.outcome == "refusal", reason="证据不足，已安全拒答。" if self.outcome == "refusal" else "",
                        refusal_code="NO_EVIDENCE" if self.outcome == "refusal" else "",
                        paragraphs=[] if self.outcome == "refusal" else [AnswerParagraph("本次可见的证据摘要。", [])])
        return PipelineResult(question, mode, answer, [], CitationCheck(True),
                              dependency_states=self.states, degraded=self.degraded,
                              degradation_reasons=["sk-synthetic-provider-error"] if self.degraded else [])


@pytest.fixture
def web_app(monkeypatch):
    streamlit = pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    import evidence_assistant.pipeline as pipeline_module
    pipeline = WebPipeline()
    streamlit.cache_resource.clear()
    monkeypatch.setattr(pipeline_module, "EvidencePipeline", lambda cfg: pipeline)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run()
    assert not app.exception
    yield app, pipeline
    streamlit.cache_resource.clear()


def submit(app, question="降压药应早上服用还是睡前服用？"):
    app.text_area[0].set_value(question)
    app.button(key="FormSubmitter:question_form-检索可信证据").click().run()
    return app


def visible_text(app):
    return "\n".join(element.value for collection in [app.markdown, app.caption, app.error, app.warning] for element in collection)


def test_web_success_uses_normalized_shared_service_and_displays_request_id(web_app):
    app, pipeline = web_app
    submit(app, "  本次临床问题  ")
    assert not app.exception
    assert pipeline.calls == [("本次临床问题", "hybrid", False)]
    assert "本次可见的证据摘要。" in visible_text(app)
    assert app.session_state["last_result"].request_id in visible_text(app)
    assert "sk-config" not in visible_text(app)


def test_web_refusal_preserves_safe_result(web_app):
    app, pipeline = web_app
    pipeline.outcome = "refusal"
    submit(app)
    assert not app.exception
    assert app.session_state["last_result"].answer.refused
    assert "证据不足，已安全拒答。" in visible_text(app)


def test_web_error_clears_previous_answer_and_recovers(web_app):
    app, pipeline = web_app
    submit(app)
    pipeline.outcome = "error"
    submit(app, "下一次问题")
    assert not app.exception
    text = visible_text(app)
    assert "本次请求处理失败" in text and "请求编号" in text
    assert "本次可见的证据摘要。" not in text
    assert "张三" not in text and "sk-private" not in text and "private.invalid" not in text
    assert "last_result" not in app.session_state
    pipeline.outcome = "success"
    submit(app, "恢复的问题")
    assert not app.exception
    assert "本次可见的证据摘要。" in visible_text(app)
    assert "本次请求处理失败" not in visible_text(app)


def test_web_invalid_submission_clears_previous_answer_without_pipeline_call(web_app):
    app, pipeline = web_app
    submit(app)
    submit(app, " \n ")
    assert not app.exception
    assert len(pipeline.calls) == 1
    assert "本次可见的证据摘要。" not in visible_text(app)
    assert "4000" in visible_text(app)


def test_web_busy_is_fixed_and_previous_answer_is_cleared(web_app, monkeypatch):
    from evidence_assistant.query_service import QueryService
    app, pipeline = web_app
    submit(app)
    guard = QueryService(pipeline)._guard
    original_init = QueryService.__init__

    def immediate(self, pipeline, **kwargs):
        return original_init(self, pipeline, max_wait_seconds=0)

    monkeypatch.setattr(QueryService, "__init__", immediate)
    guard.acquire("test-request", 0, 0)
    try:
        submit(app, "繁忙时的问题")
    finally:
        guard.release()
    assert not app.exception
    assert "服务繁忙" in visible_text(app) and "请求编号" in visible_text(app)
    assert "本次可见的证据摘要。" not in visible_text(app)
    assert len(pipeline.calls) == 1


@pytest.mark.parametrize("states,label", [
    ({"pubmed": DependencyState("success", "completed", result_count=2)}, "已获取证据"),
    ({"pubmed": DependencyState("empty", "no_results")}, "已尝试，无结果"),
    ({"pubmed": DependencyState("error", "timeout")}, "调用失败"),
    ({"pubmed": DependencyState("not_attempted", "local_evidence_sufficient")}, "未尝试"),
    ({"pubmed": DependencyState("disabled", "disabled")}, "未启用"),
])
def test_web_live_metric_uses_structured_dependency_states(web_app, states, label):
    app, pipeline = web_app
    pipeline.states = states
    submit(app)
    metric = next(metric for metric in app.metric if metric.label == "实时源")
    assert metric.value == label


def test_web_fallback_state_has_fixed_reason_without_opaque_provider_message(web_app):
    app, pipeline = web_app
    pipeline.states = {"generator": DependencyState("fallback", "timeout", actual_backend="extractive")}
    pipeline.degraded = True
    submit(app)
    assert not app.exception
    text = visible_text(app)
    assert "生成器：已回退" in text and "超时" in text
    assert "sk-synthetic-provider-error" not in text
