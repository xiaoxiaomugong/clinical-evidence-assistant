from __future__ import annotations

import re
from typing import List, Tuple

from .candidate_pool import research_family_id
from .schemas import Answer, CitationCheck, Entry, EvidenceGateResult, QuerySpec


def refusal_answer(gate: EvidenceGateResult, generator: str = "none") -> Answer:
    return Answer(
        refused=True,
        reason=gate.reason,
        refusal_code=gate.code,
        found=list(gate.found),
        missing=list(gate.missing),
        next_steps=list(gate.next_steps),
        generator=generator,
    )


def assess_safety(spec: QuerySpec) -> EvidenceGateResult:
    if spec.contains_phi:
        return EvidenceGateResult(
            refused=True,
            code="PHI_BLOCKED",
            reason="问题中疑似包含可识别个人信息，系统未执行检索或外部调用。",
            found=["检测到姓名、病历号、联系方式、证件号或完整出生日期等风险模式。"],
            missing=["缺少去标识化后的医学问题。"],
            next_steps=["删除可识别信息，仅保留年龄段、疾病、干预和结局后重新提问。"],
        )
    if spec.personalized_treatment:
        return EvidenceGateResult(
            refused=True,
            code="PERSONALIZED_TREATMENT",
            reason="该问题涉及个体化药物、剂量、停药或换药决策，超出本教学证据助手的边界。",
            found=["系统可以提供公开指南与研究的一般性证据摘要。"],
            missing=["缺少执业医师基于完整病史、检查、合并症和用药信息的评估。"],
            next_steps=["请由执业医师评估；如需继续，可改问相关干预的一般证据、适用范围与局限。"],
        )
    if spec.out_of_scope:
        return EvidenceGateResult(
            refused=True,
            code="OUT_OF_SCOPE",
            reason="当前系统仅覆盖成人心脑血管病、血脂、高血压和糖尿病证据。",
            missing=["问题不在当前已声明的语料覆盖范围内。"],
            next_steps=["请改为范围内的公开证据问题，或使用覆盖该专科的资料库。"],
        )
    if re.search(r"\bxyz\b|虚构|不存在的药|X\s*疗法|尚未上市的新疗法", spec.original, re.IGNORECASE):
        return EvidenceGateResult(
            refused=True,
            code="UNVERIFIABLE_INTERVENTION",
            reason="问题中的疗法或标识无法被核实，不能据此形成结论。",
            missing=["缺少可回查的真实药物、试验注册或文献标识。"],
            next_steps=["请提供通用名、PMID、DOI、NCT 编号或其他可核验来源。"],
        )
    return EvidenceGateResult(refused=False)


def _evidence_summary(entries: List[Entry]) -> Tuple[List[str], int]:
    sources = {research_family_id(entry) for entry in entries if research_family_id(entry)}
    levels = sorted({entry.evidence_level for entry in entries if entry.evidence_level})
    return levels, len(sources)


def assess_evidence(
    spec: QuerySpec,
    entries: List[Entry],
    threshold: float = 0.18,
    minimum_sources: int = 3,
) -> EvidenceGateResult:
    levels, source_count = _evidence_summary(entries)
    found = [
        f"检索到 {len(entries)} 个候选片段，来自 {source_count} 个独立来源。",
        f"证据类型：{'、'.join(levels) if levels else '未标注'}。",
    ]
    if not entries:
        return EvidenceGateResult(
            refused=True,
            code="NO_EVIDENCE",
            reason="检索支路未返回可引用证据。",
            found=["当前查询未命中可引用条目。"],
            missing=["缺少与问题直接相关且可回查的证据。"],
            next_steps=["缩小人群、干预和结局范围，或补查近期指南、系统综述和 RCT。"],
            independent_source_count=0,
        )

    top_score = entries[0].score
    relevant_topics = set(spec.domains)
    topic_match = any(entry.topic in relevant_topics for entry in entries[:3] if entry.topic)
    if top_score < threshold or (relevant_topics and not topic_match):
        return EvidenceGateResult(
            refused=True,
            code="LOW_RELEVANCE",
            reason="当前候选与问题的直接相关性不足，不能把边缘材料包装成结论。",
            found=found,
            missing=["缺少能直接覆盖目标人群、干预或结局的证据。"],
            next_steps=["使用更具体的 PICO 条件重新检索，并优先补查预期证据类型。"],
            independent_source_count=source_count,
            evidence_types=levels,
        )

    if source_count < minimum_sources:
        return EvidenceGateResult(
            refused=True,
            code="INSUFFICIENT_SOURCES",
            reason="独立来源数量不足，当前结果只能作为检索线索，不能形成确定结论。",
            found=found,
            missing=[f"至少需要 {minimum_sources} 个独立且可回查来源，当前仅有 {source_count} 个。"],
            next_steps=["补查近期指南、系统综述或代表性 RCT，并按 PMID/DOI/NCT 去重。"],
            independent_source_count=source_count,
            evidence_types=levels,
        )

    expected = set(spec.expected_evidence_types)
    if expected and not expected.intersection(levels):
        return EvidenceGateResult(
            refused=True,
            code="MISSING_EVIDENCE_TYPE",
            reason="候选证据未命中问题所需的证据类型。",
            found=found,
            missing=[f"预期至少命中以下一种类型：{'、'.join(spec.expected_evidence_types)}。"],
            next_steps=["保留现有结果作为线索，并定向补查缺失的指南、系统综述或 RCT。"],
            independent_source_count=source_count,
            evidence_types=levels,
        )

    conflict_markers = ("证据冲突", "结论不一致", "conflicting evidence", "inconsistent findings")
    if any(any(marker in entry.text.lower() for marker in conflict_markers) for entry in entries[:5]):
        return EvidenceGateResult(
            refused=True,
            code="UNRESOLVED_CONFLICT",
            reason="候选证据存在尚未解释的冲突，系统不会自动选边。",
            found=found,
            missing=["缺少对研究人群、时间、结局和证据等级差异的解释。"],
            next_steps=["并列核对冲突来源，补充方法学差异后再形成带边界的结论。"],
            independent_source_count=source_count,
            evidence_types=levels,
        )

    return EvidenceGateResult(
        refused=False,
        found=found,
        independent_source_count=source_count,
        evidence_types=levels,
    )


def decide_pre(spec: QuerySpec, entries: List[Entry], threshold: float = 0.18) -> Tuple[bool, str]:
    """Backward-compatible tuple wrapper used by older integrations."""
    safety = assess_safety(spec)
    gate = safety if safety.refused else assess_evidence(spec, entries, threshold)
    return gate.refused, gate.reason


def assess_post(
    check: CitationCheck,
    answer: Answer,
    failure_threshold: float = 0.5,
) -> EvidenceGateResult:
    if answer.refused:
        return EvidenceGateResult(
            refused=True,
            code=answer.refusal_code or "GENERATOR_REFUSAL",
            reason=answer.reason or "生成模型判断现有证据不足。",
            found=answer.found,
            missing=answer.missing,
            next_steps=answer.next_steps,
        )
    if not answer.paragraphs:
        return EvidenceGateResult(
            refused=True,
            code="NO_SUPPORTED_CLAIMS",
            reason="校验后没有可展示的受支持陈述。",
            found=[f"生成器最初返回 {answer.original_paragraph_count} 条陈述。"],
            missing=["所有核心陈述都缺少直接、数值一致的引用支持。"],
            next_steps=["补充直接证据或降低陈述强度后重新生成。"],
        )
    if check.failure_ratio > failure_threshold:
        return EvidenceGateResult(
            refused=True,
            code="CITATION_FAILURE",
            reason="引用校验失败比例过高，证据可靠性不足。",
            found=[f"最终保留 {len(answer.paragraphs)} 条受支持陈述。"],
            missing=["过多原始陈述或引用未通过映射、存在性、支持性或数值一致性检查。"],
            next_steps=["缩小回答范围，补充更直接的证据并重新生成。"],
        )
    return EvidenceGateResult(refused=False)


def decide_post(
    check: CitationCheck,
    answer: Answer,
    failure_threshold: float = 0.5,
) -> Tuple[bool, str]:
    gate = assess_post(check, answer, failure_threshold)
    return gate.refused, gate.reason
