from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, List

from .schemas import QuerySpec


DOMAIN_TERMS: Dict[str, List[str]] = {
    "高血压": ["高血压", "血压", "降压", "hypertension", "antihypertensive", "acei", "arb", "ccb", "利尿剂"],
    "血脂": ["血脂", "胆固醇", "ldl", "hdl", "甘油三酯", "他汀", "statin", "lipid", "cholesterol"],
    "糖尿病": ["糖尿病", "血糖", "胰岛素", "glp-1", "sglt2", "diabetes", "metformin", "二甲双胍"],
    "脑卒中": ["卒中", "中风", "tia", "脑梗", "脑出血", "stroke", "阿司匹林", "氯吡格雷"],
    "心脑血管": ["心血管", "冠心病", "心梗", "心衰", "动脉粥样硬化", "ascvd", "cardiovascular", "地中海饮食", "限钠", "低盐"],
}

ENGLISH_EXPANSIONS = {
    "高血压": "hypertension antihypertensive treatment",
    "血压": "blood pressure",
    "降压药": "antihypertensive medication",
    "血脂": "dyslipidemia lipid management",
    "胆固醇": "cholesterol",
    "他汀": "statin",
    "糖尿病": "type 2 diabetes mellitus",
    "肥胖": "obesity weight management",
    "脑卒中": "stroke secondary prevention",
    "卒中": "stroke",
    "中风": "stroke",
    "阿司匹林": "aspirin",
    "氯吡格雷": "clopidogrel",
    "地中海饮食": "Mediterranean diet",
    "限钠": "dietary sodium reduction",
    "低盐": "dietary sodium reduction",
    "早上": "morning dosing",
    "睡前": "bedtime dosing",
    "肌肉": "muscle symptoms",
    "副作用": "adverse effects",
}

ANIMAL_TERMS = {"宠物", "犬", "狗", "猫", "兽医", "animal", "canine", "feline"}

PHI_PATTERNS = [
    re.compile(r"(?:姓名|患者姓名)\s*[：:]\s*[\u4e00-\u9fff·]{2,8}"),
    re.compile(r"(?:病历号|住院号|门诊号|医保号)\s*[：:]?\s*[A-Za-z0-9-]{4,}"),
    re.compile(r"(?:身份证(?:号码?)?|证件号码?)\s*[：:]?\s*\d{15,18}[0-9Xx]?"),
    re.compile(r"(?:手机号|电话|联系方式)\s*[：:]?\s*(?:\+?86[- ]?)?1\d{10}"),
    re.compile(r"(?:生日|出生日期)\s*[：:]?\s*(?:19|20)\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?"),
]

PERSONALIZED_TREATMENT_PATTERNS = [
    re.compile(r"(?:我|本人|我爷爷|我奶奶|我父亲|我母亲|这个患者).{0,18}(?:该|要不要|能不能|是否应该).{0,8}(?:吃|用|停|换|加|减).{0,8}(?:药|剂量)"),
    re.compile(r"(?:每天|每次).{0,8}(?:吃|服|用).{0,8}(?:多少|几片|几毫克|mg)"),
    re.compile(r"(?:停药|换药|加量|减量|具体剂量|开处方|开什么药)"),
]


def _unique(items: List[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        item = item.strip()
        if item and item.lower() not in seen:
            seen.add(item.lower())
            result.append(item)
    return result


def _basic_pico(question: str) -> Dict[str, str]:
    population = "成人"
    if "老年" in question or re.search(r"\b(?:6[5-9]|[7-9]\d)\s*岁", question):
        population = "老年成人"
    elif "孕" in question:
        population = "妊娠人群"
    interventions = [zh for zh in ENGLISH_EXPANSIONS if zh in question]
    comparison = ""
    if " vs " in question.lower() or "对比" in question or "比较" in question:
        comparison = "问题中指定的对照方案"
    return {
        "P": population,
        "I": "、".join(interventions[:4]),
        "C": comparison,
        "O": "临床获益、风险与适用条件",
    }


def redact_phi(question: str) -> str:
    redacted = question
    for pattern in PHI_PATTERNS:
        redacted = pattern.sub("[已删除可识别信息]", redacted)
    return redacted


def contains_phi(question: str) -> bool:
    return any(pattern.search(question) for pattern in PHI_PATTERNS)


def _is_personalized_treatment(question: str) -> bool:
    return any(pattern.search(question) for pattern in PERSONALIZED_TREATMENT_PATTERNS)


def _expected_evidence_types(question: str) -> List[str]:
    lower = question.lower()
    expected: List[str] = []
    if "指南" in question or "共识" in question or "guideline" in lower:
        expected.append("Guideline")
    if any(term in lower for term in ("系统综述", "meta", "荟萃", "review")):
        expected.extend(["Meta-analysis", "Review"])
    if any(term in lower for term in ("rct", "随机", "randomized")):
        expected.append("RCT")
    if any(term in lower for term in ("临床试验", "试验注册", "nct")):
        expected.extend(["RCT", "ClinicalTrial"])
    if not expected and any(term in lower for term in ("对比", "比较", " vs ", "疗效", "副作用", "风险有多大")):
        expected.extend(["Meta-analysis", "RCT"])
    return _unique(expected)


def _time_range(question: str) -> tuple:
    current_year = datetime.now().year
    match = re.search(r"近\s*(\d{1,2})\s*年", question)
    if match:
        return current_year - int(match.group(1)), current_year
    match = re.search(r"((?:19|20)\d{2})\s*年?(?:以后|之后|至今)", question)
    if match:
        return int(match.group(1)), current_year
    if any(term in question.lower() for term in ("最新", "最近", "当前", "目前", "up-to-date")):
        return current_year - 10, current_year
    return None, None


def rewrite(question: str, domains: List[str] = None) -> QuerySpec:
    question = question.strip()
    safe_query = redact_phi(question)
    lower = safe_query.lower()
    detected = []
    allowed = set(domains or DOMAIN_TERMS.keys())
    for domain, terms in DOMAIN_TERMS.items():
        if domain in allowed and any(term in lower for term in terms):
            detected.append(domain)

    animal_scope = any(term in lower for term in ANIMAL_TERMS)
    out_of_scope = animal_scope or not detected

    local_terms = [safe_query]
    english_terms = []
    for zh, english in ENGLISH_EXPANSIONS.items():
        if zh in lower:
            local_terms.extend([zh, english])
            english_terms.append(english)
    for domain in detected:
        local_terms.extend(DOMAIN_TERMS[domain])
        english_terms.extend(term for term in DOMAIN_TERMS[domain] if re.search(r"[a-z]", term))

    english_query = " ".join(_unique(english_terms))
    if not english_query:
        english_query = safe_query
    main_query = f"({english_query}) AND (guideline OR trial OR meta-analysis)"
    guideline_query = f"({english_query}) AND Guideline[pt]"
    time_from, time_to = _time_range(safe_query)
    needs_latest = any(term in lower for term in ("最新", "最近", "当前", "目前", "up-to-date"))

    return QuerySpec(
        original=question,
        pico=_basic_pico(safe_query),
        api_queries=_unique([main_query, guideline_query]),
        local_terms=_unique(local_terms),
        domains=detected,
        expected_evidence_types=_expected_evidence_types(safe_query),
        time_from=time_from,
        time_to=time_to,
        needs_latest=needs_latest,
        personalized_treatment=_is_personalized_treatment(safe_query),
        contains_phi=contains_phi(question),
        safe_query=safe_query,
        out_of_scope=out_of_scope,
    )
