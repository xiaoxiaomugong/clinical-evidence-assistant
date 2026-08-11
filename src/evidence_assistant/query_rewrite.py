from __future__ import annotations

import re
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


def rewrite(question: str, domains: List[str] = None) -> QuerySpec:
    question = question.strip()
    lower = question.lower()
    detected = []
    allowed = set(domains or DOMAIN_TERMS.keys())
    for domain, terms in DOMAIN_TERMS.items():
        if domain in allowed and any(term in lower for term in terms):
            detected.append(domain)

    animal_scope = any(term in lower for term in ANIMAL_TERMS)
    out_of_scope = animal_scope or not detected

    local_terms = [question]
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
        english_query = question
    main_query = f"({english_query}) AND (guideline OR trial OR meta-analysis)"
    guideline_query = f"({english_query}) AND Guideline[pt]"

    return QuerySpec(
        original=question,
        pico=_basic_pico(question),
        api_queries=_unique([main_query, guideline_query]),
        local_terms=_unique(local_terms),
        domains=detected,
        out_of_scope=out_of_scope,
    )
