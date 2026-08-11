from __future__ import annotations

import math
import re
from collections import Counter
from typing import Dict, Iterable, List, Sequence, Tuple


STOPWORDS = {
    "的", "了", "和", "与", "或", "是否", "如何", "什么", "哪些", "有", "对", "在",
    "患者", "病人", "研究", "证据", "指南", "治疗", "用药", "the", "a", "an", "of",
    "and", "or", "to", "in", "for", "with", "is", "are", "what", "how",
}


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def tokenize(text: str) -> List[str]:
    text = normalize(text)
    english = re.findall(r"[a-z][a-z0-9+.-]{1,}", text)
    chinese_runs = re.findall(r"[\u4e00-\u9fff]+", text)
    chinese: List[str] = []
    for run in chinese_runs:
        if len(run) <= 2:
            chinese.append(run)
        else:
            chinese.extend(run[i : i + 2] for i in range(len(run) - 1))
    numeric = re.findall(r"\b\d+(?:\.\d+)?\b", text)
    return [token for token in english + chinese + numeric if token not in STOPWORDS]


def _idf(documents: Sequence[List[str]]) -> Dict[str, float]:
    doc_count = max(len(documents), 1)
    freq: Counter = Counter()
    for tokens in documents:
        freq.update(set(tokens))
    return {term: math.log((doc_count + 1) / (count + 1)) + 1 for term, count in freq.items()}


def bm25_scores(query: str, documents: Sequence[str], k1: float = 1.5, b: float = 0.75) -> List[float]:
    tokenized = [tokenize(document) for document in documents]
    if not tokenized:
        return []
    query_tokens = tokenize(query)
    avg_len = sum(len(tokens) for tokens in tokenized) / max(len(tokenized), 1)
    doc_freq: Counter = Counter()
    for tokens in tokenized:
        doc_freq.update(set(tokens))
    scores: List[float] = []
    for tokens in tokenized:
        counts = Counter(tokens)
        score = 0.0
        for term in query_tokens:
            if not counts[term]:
                continue
            idf = math.log(1 + (len(tokenized) - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
            numerator = counts[term] * (k1 + 1)
            denominator = counts[term] + k1 * (1 - b + b * len(tokens) / max(avg_len, 1))
            score += idf * numerator / denominator
        scores.append(score)
    maximum = max(scores, default=0.0)
    return [score / maximum if maximum else 0.0 for score in scores]


def cosine_scores(query: str, documents: Sequence[str]) -> List[float]:
    tokenized = [tokenize(query)] + [tokenize(document) for document in documents]
    weights = _idf(tokenized)

    def vector(tokens: Iterable[str]) -> Dict[str, float]:
        counts = Counter(tokens)
        return {term: count * weights.get(term, 1.0) for term, count in counts.items()}

    query_vector = vector(tokenized[0])
    query_norm = math.sqrt(sum(value * value for value in query_vector.values())) or 1.0
    scores: List[float] = []
    for tokens in tokenized[1:]:
        document_vector = vector(tokens)
        document_norm = math.sqrt(sum(value * value for value in document_vector.values())) or 1.0
        dot = sum(value * document_vector.get(term, 0.0) for term, value in query_vector.items())
        scores.append(dot / (query_norm * document_norm))
    return scores


def ranked_indices(scores: Sequence[float], limit: int) -> List[int]:
    return sorted(range(len(scores)), key=lambda index: scores[index], reverse=True)[:limit]


def rrf_fuse(rankings: Sequence[Sequence[int]], k: int = 60) -> Dict[int, float]:
    fused: Dict[int, float] = {}
    for ranking in rankings:
        for rank, index in enumerate(ranking, start=1):
            fused[index] = fused.get(index, 0.0) + 1.0 / (k + rank)
    maximum = max(fused.values(), default=0.0)
    return {index: score / maximum if maximum else 0.0 for index, score in fused.items()}


def term_overlap(left: str, right: str) -> float:
    left_tokens, right_tokens = set(tokenize(left)), set(tokenize(right))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens)


def split_text(text: str, max_chars: int = 900) -> List[str]:
    sentences = [part.strip() for part in re.split(r"(?<=[。！？.!?])\s*", text) if part.strip()]
    chunks: List[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current += (" " if current else "") + sentence
    if current:
        chunks.append(current)
    return chunks or ([text.strip()] if text.strip() else [])
