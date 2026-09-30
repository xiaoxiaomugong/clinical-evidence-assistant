"""Conservative question coverage for the small offline evidence corpus.

This checks whether a passage covers the requested subject, not whether its
clinical assertion is true. Citation verification remains a separate gate.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple

from .schemas import Entry, QuerySpec


# Concepts describe interventions and outcomes, not individual evaluation
# questions. A disease name alone is deliberately insufficient for a focused
# question. Longer aliases are tested first to avoid substring ambiguity.
CONCEPTS = {
    "mediterranean": ("地中海饮食", "mediterranean diet"),
    "sodium": ("限钠", "低盐", "钠摄入", "尿钠", "sodium"),
    "dosing_time": ("早上服用", "早晨服用", "晚间服用", "晚上服用", "睡前服用", "服药时间", "早上", "早晨", "晚间", "晚上", "睡前", "morning dosing", "bedtime dosing"),
    "antihypertensive": ("降压药", "抗高血压药", "antihypertensive"),
    "statin": ("他汀", "statin"),
    "muscle": ("肌肉症状", "肌肉疼痛", "肌痛", "肌肉", "无力", "myalgia"),
    "aspirin": ("阿司匹林", "aspirin"),
    "clopidogrel": ("氯吡格雷", "clopidogrel"),
    "glp1": ("glp-1", "胰高血糖素样肽"),
    "sglt2": ("sglt2", "sglt-2"),
    "insulin": ("胰岛素", "insulin"),
    "ldl": ("ldl-c", "低密度脂蛋白"),
    "heart_failure": ("心衰", "心力衰竭", "heart failure"),
    "kidney": ("慢性肾病", "肾病", "肾功能", "ckd"),
    "bleeding": ("出血风险", "出血", "bleeding"),
    "cardiovascular_outcome": ("心血管结局", "心血管事件", "心血管风险", "心血管", "血管死亡", "cardiovascular outcome", "cardiovascular event"),
}

_GENERIC_CODES = {"rct", "pico", "pmid", "doi", "nct", "who", "ada", "aha", "asa", "ascvd", "tia"}
_POPULATION_CONCEPTS = {
    "pregnancy": ("妊娠", "孕妇", "孕期"),
    "older": ("老年", "高龄"),
    "coronary": ("冠心病", "冠状动脉疾病"),
}


def _contains(text: str, aliases: Tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(alias in lower for alias in aliases)


@dataclass(frozen=True)
class QuestionFocus:
    concepts: Tuple[str, ...]
    literals: Tuple[str, ...]
    populations: Tuple[str, ...]
    domains: Tuple[str, ...]
    broad_diet: bool = False

    @classmethod
    def from_spec(cls, spec: QuerySpec) -> "QuestionFocus":
        question = spec.safe_query or spec.original
        lower = question.lower()
        concepts = tuple(key for key, aliases in CONCEPTS.items() if _contains(lower, aliases))
        # An unfamiliar named pathway/drug/study must be present in evidence;
        # broad hypertension text cannot silently answer it.
        known_text = question
        for aliases in CONCEPTS.values():
            for alias in sorted(aliases, key=len, reverse=True):
                known_text = re.sub(re.escape(alias), " ", known_text, flags=re.I)
        codes = [token.lower() for token in re.findall(r"\b[A-Za-z][A-Za-z0-9-]{2,}\b", known_text)
                 if token.lower() not in _GENERIC_CODES and (token.isupper() or any(char.isdigit() for char in token))]
        chinese_foci = re.findall(r"(?:中的|关于|针对)\s*([\u4e00-\u9fff]{2,12})\s*(?:通路|机制|疗法)", question)
        literals = tuple(dict.fromkeys(codes + chinese_foci))
        population_text = " ".join(re.findall(r"(?:人群|population)\s*[：:]\s*([^\n]+)", question, flags=re.I))
        populations = tuple(key for key, aliases in _POPULATION_CONCEPTS.items()
                            if _contains(population_text, aliases))
        broad_diet = any(phrase in question for phrase in ("饮食模式", "膳食模式")) and "干预：" not in question
        return cls(concepts, literals, populations, tuple(spec.domains), broad_diet)

    def covers(self, text: str) -> bool:
        main = text.split("例外：", 1)[0].lower()
        if self.broad_diet:
            if not any(_contains(main, CONCEPTS[key]) for key in self.concepts):
                return False
            if not any(term in main for term in ("饮食", "膳食", "钠")):
                return False
        elif not all(_contains(main, CONCEPTS[key]) for key in self.concepts):
            return False
        if not all(literal in main for literal in self.literals):
            return False
        for population in self.populations:
            if population == "pregnancy":
                if not _contains(main, _POPULATION_CONCEPTS[population]) or "非妊娠" in main or "不用于妊娠" in main:
                    return False
            elif not _contains(main, _POPULATION_CONCEPTS[population]):
                return False
        return True

    def direct(self, entry: Entry) -> bool:
        if not self.covers(entry.text):
            return False
        if self.broad_diet:
            return entry.topic in self.domains
        if self.concepts or self.literals or self.populations:
            return True
        # Wide questions still need a disease/field match, rather than making
        # every evidence item a direct answer.
        return entry.topic in self.domains or any(domain in entry.text for domain in self.domains)

    def background(self, entry: Entry) -> bool:
        return entry.topic in self.domains


def partition(spec: QuerySpec, entries: List[Entry]) -> Tuple[List[Entry], List[Entry]]:
    focus = QuestionFocus.from_spec(spec)
    direct = [entry for entry in entries if focus.direct(entry)]
    background = [entry for entry in entries if entry not in direct and focus.background(entry)]
    return direct, background
