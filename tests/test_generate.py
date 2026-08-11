from config import Settings
from evidence_assistant.generate import call_llm


def test_call_llm_disables_thinking_for_deepseek(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"refused":false,"paragraphs":[],"limitations":[]}'
                            )
                        }
                    }
                ]
            }

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr("evidence_assistant.generate.requests.post", fake_post)
    cfg = Settings(
        llm_api_key="test-key",
        llm_base_url="https://api.deepseek.com",
        llm_model="deepseek-v4-flash",
    )

    answer = call_llm("json connection test", cfg)

    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["json"]["thinking"] == {"type": "disabled"}
    assert answer.generator == "llm:deepseek-v4-flash"
