from __future__ import annotations

import re
from typing import List, Tuple

from .schemas import Answer, CitationCheck, Entry, QuerySpec


def decide_pre(spec: QuerySpec, entries: List[Entry], threshold: float = 0.18) -> Tuple[bool, str]:
    if spec.out_of_scope:
        return True, "当前系统仅覆盖成人心脑血管病、血脂、高血压和糖尿病证据；请换一个范围内的问题。"
    if re.search(r"\bxyz\b|虚构|不存在的药|X\s*疗法|尚未上市的新疗法", spec.original, re.IGNORECASE):
        return True, "没有检索到可核实的真实疗法或文献，当前证据不足，不能据此作答。"
    if not entries:
        return True, "检索支路未返回可引用证据，请稍后重试或换一种问法。"
    top_score = entries[0].score
    relevant_topics = set(spec.domains)
    topic_match = any(entry.topic in relevant_topics for entry in entries[:3] if entry.topic)
    if top_score < threshold or (relevant_topics and not topic_match):
        return True, "当前检索到的证据与问题相关性不足，无法形成可靠回答。"
    return False, ""


def decide_post(
    check: CitationCheck,
    answer: Answer,
    failure_threshold: float = 0.5,
) -> Tuple[bool, str]:
    if answer.refused:
        return True, answer.reason or "生成模型判断现有证据不足。"
    if not answer.paragraphs:
        return True, "生成结果没有包含可验证的核心结论。"
    if check.failure_ratio > failure_threshold:
        return True, "引用校验失败比例过高，证据可靠性不足。"
    if len(check.stripped_paragraphs) >= len(answer.paragraphs):
        return True, "校验后所有核心结论均失去有效引用，已停止输出。"
    return False, ""
