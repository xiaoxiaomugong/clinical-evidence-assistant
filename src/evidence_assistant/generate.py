from __future__ import annotations

import json
from typing import List

import requests

from config import Settings, settings
from .schemas import Answer, AnswerParagraph, Entry


SYSTEM_PROMPT = """你是临床证据助手。只基于提供的候选证据回答，不使用记忆补充事实。
规则：
1. 每个结论必须提供 citation_ids，编号只能来自可引用列表。
2. 禁止编造文献、期刊、证据等级、数值或结论。
3. 证据不足时输出 refused=true。
4. 区分指南推荐与研究提示，保留适用人群和例外。
5. ClinicalTrial 若未完成，不得表述为已经证实疗效。
6. 只输出 JSON：{"refused":false,"paragraphs":[{"text":"结论","citation_ids":[1]}],"limitations":["局限"]}。"""


def build_prompt(question: str, entries: List[Entry]) -> str:
    evidence = []
    for entry in entries:
        metadata = [entry.evidence_level, entry.source]
        if entry.year:
            metadata.append(str(entry.year))
        if entry.status:
            metadata.append(f"status={entry.status}")
        evidence.append(
            f"[{entry.citation_number}] {entry.title}\n"
            f"元数据：{' | '.join(metadata)}\n"
            f"内容：{entry.text}\n"
            f"URL：{entry.url}"
        )
    return f"{SYSTEM_PROMPT}\n\n用户问题：{question}\n\n可引用列表：\n" + "\n\n".join(evidence)


def _parse_answer(payload: dict, generator: str) -> Answer:
    refused = bool(payload.get("refused", False))
    paragraphs = []
    for item in payload.get("paragraphs", []):
        text = str(item.get("text", "")).strip()
        citation_ids = []
        for value in item.get("citation_ids", []):
            try:
                citation_ids.append(int(value))
            except (TypeError, ValueError):
                continue
        if text:
            paragraphs.append(AnswerParagraph(text=text, citation_ids=citation_ids))
    return Answer(
        refused=refused,
        paragraphs=paragraphs,
        reason=str(payload.get("reason", "")),
        limitations=[str(item) for item in payload.get("limitations", [])],
        generator=generator,
    )


def call_llm(prompt: str, cfg: Settings = settings) -> Answer:
    if not cfg.llm_api_key:
        raise RuntimeError("LLM_API_KEY is not configured")
    request_payload = {
        "model": cfg.llm_model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    }
    if cfg.llm_model.startswith("deepseek-") or "api.deepseek.com" in cfg.llm_base_url:
        # DeepSeek V4 defaults to thinking mode. This application expects the
        # JSON response in message.content, so use its non-thinking mode.
        request_payload["thinking"] = {"type": "disabled"}
    response = requests.post(
        f"{cfg.llm_base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {cfg.llm_api_key}", "Content-Type": "application/json"},
        json=request_payload,
        timeout=45,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return _parse_answer(json.loads(content), generator=f"llm:{cfg.llm_model}")


def extractive_answer(question: str, entries: List[Entry], max_paragraphs: int = 4) -> Answer:
    if not entries:
        return Answer(refused=True, reason="没有可引用证据。", generator="extractive")
    selected: List[Entry] = []
    seen_text = set()
    for entry in entries:
        fingerprint = entry.text[:80]
        if fingerprint in seen_text:
            continue
        selected.append(entry)
        seen_text.add(fingerprint)
        if len(selected) >= max_paragraphs:
            break
    paragraphs = [
        AnswerParagraph(text=entry.text, citation_ids=[entry.citation_number])
        for entry in selected
    ]
    limitations = [
        "当前为离线可审计模式：回答直接摘取经核对的知识页或文献摘要，不进行超出证据的推断。",
        "内容仅供学习与研究，不构成诊疗建议；个体决策需由临床专业人员结合完整病史与检查完成。",
    ]
    return Answer(refused=False, paragraphs=paragraphs, limitations=limitations, generator="extractive")


def generate(question: str, entries: List[Entry], cfg: Settings = settings) -> Answer:
    prompt = build_prompt(question, entries)
    if cfg.llm_api_key:
        try:
            return call_llm(prompt, cfg)
        except (requests.RequestException, KeyError, ValueError, json.JSONDecodeError):
            pass
    return extractive_answer(question, entries)
