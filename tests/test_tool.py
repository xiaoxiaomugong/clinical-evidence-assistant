import json

import pytest

from evidence_assistant.tool import ClinicalEvidenceTool


def test_agent_tool_returns_complete_json_serializable_result():
    payload = ClinicalEvidenceTool().query(
        "降压药应早上服用还是睡前服用？",
        mode="hybrid",
        enable_live_apis=False,
    )

    assert payload["schema_version"] == "1.0"
    assert payload["status"] == "answered"
    assert payload["answer"]["refused"] is False
    assert payload["entries"]
    assert payload["citation_check"]["valid"] is True
    assert payload["disclaimer"]
    json.dumps(payload, ensure_ascii=False)


def test_agent_tool_preserves_pipeline_safety_refusal():
    payload = ClinicalEvidenceTool().query(
        "姓名：张三，病历号 A123456，高血压该怎么办？",
        enable_live_apis=True,
    )

    assert payload["status"] == "refused"
    assert payload["answer"]["refused"] is True
    assert payload["used_live_api"] is False
    assert payload["entries"] == []


@pytest.mark.parametrize(
    "question,mode,error",
    [
        ("   ", "hybrid", "不能为空"),
        ("高血压证据", "invalid", "不支持的 mode"),
    ],
)
def test_agent_tool_validates_inputs(question, mode, error):
    tool = ClinicalEvidenceTool()
    with pytest.raises(ValueError, match=error):
        tool.query(question, mode=mode)
