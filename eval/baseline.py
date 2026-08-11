from __future__ import annotations

import json

import requests

from config import Settings, settings
from evidence_assistant.generate import COMMON_SAFETY_RULES


BASELINE_PROMPT = f"""你是通用大模型基线。不得使用检索工具或外部资料。
{COMMON_SAFETY_RULES}
公平评估约束：不得伪造已经核对的来源；由于本臂没有 evidence map，citation_ids 必须为空。
只输出 JSON：{{"refused":false,"claims":[{{"text":"原子陈述","citation_ids":[],"claim_type":"effect","certainty":"low"}}],"limitations":["未使用外部检索，来源不可核验"],"found":[],"missing":[],"next_steps":[]}}。"""


def call_baseline(question: str, cfg: Settings = settings) -> dict:
    if not cfg.llm_api_key:
        raise RuntimeError("运行纯 LLM 基线需要 LLM_API_KEY")
    response = requests.post(
        f"{cfg.llm_base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {cfg.llm_api_key}", "Content-Type": "application/json"},
        json={
            "model": cfg.llm_model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": BASELINE_PROMPT},
                {"role": "user", "content": question},
            ],
        },
        timeout=45,
    )
    response.raise_for_status()
    return json.loads(response.json()["choices"][0]["message"]["content"])
