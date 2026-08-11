from __future__ import annotations

import json

import requests

from config import Settings, settings


BASELINE_PROMPT = """你是通用大模型基线。不得使用检索工具。回答临床问题，并按 JSON 输出：
{"refused":false,"paragraphs":[{"text":"结论","citation_ids":[1]}],"references":[{"number":1,"title":"来源标题","url":"URL"}]}
如果不知道，输出 refused=true。不要假装已核对来源。"""


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
