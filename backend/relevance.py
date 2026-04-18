from __future__ import annotations

import re
from typing import Iterable, List, Set


STOPWORDS = {
    "should",
    "would",
    "could",
    "buy",
    "not",
    "wait",
    "worth",
    "compare",
    "comparison",
    "best",
    "good",
    "need",
    "this",
    "that",
    "with",
    "from",
    "into",
    "your",
    "have",
    "about",
    "what",
    "which",
    "when",
    "where",
    "why",
    "how",
    "for",
    "and",
    "the",
    "are",
    "learn",
}


def extract_keywords(query: str) -> Set[str]:
    tokens = re.findall(r"[a-z0-9]+", query.lower())
    keywords = {
        token
        for token in tokens
        if len(token) >= 4 and not token.isdigit() and token not in STOPWORDS
    }
    if keywords:
        return keywords
    return {
        token
        for token in tokens
        if len(token) >= 3 and not token.isdigit() and token not in STOPWORDS
    }


def relevance_score(query: str, texts: Iterable[str]) -> float:
    keywords = extract_keywords(query)
    if not keywords:
        return 1.0

    haystack = " ".join(texts).lower()
    matched = sum(1 for keyword in keywords if keyword in haystack)
    if matched == 0:
        return 0.0
    return matched / len(keywords)


def intent_terms(query: str) -> Set[str]:
    lower = query.lower()
    terms: Set[str] = set()
    if "buy" in lower or "worth" in lower:
        terms.update(
            {
                "buy",
                "worth",
                "review",
                "price",
                "cost",
                "upgrade",
                "recommend",
                "wait",
                "worth it",
            }
        )
    if "learn" in lower:
        terms.update({"learn", "beginner", "career", "roadmap", "worth"})
    if "switch" in lower or "move" in lower:
        terms.update({"switch", "move", "transition", "from", "to"})
    if "compare" in lower or "vs" in lower:
        terms.update({"compare", "comparison", "vs", "versus"})
    return terms


def is_relevant(query: str, texts: List[str], min_score: float = 0.34) -> bool:
    score = relevance_score(query, texts)
    if score < min_score:
        return False

    haystack = " ".join(texts).lower()
    if "i am not oop" in haystack or "originally posted to" in haystack:
        return False

    required_intent = intent_terms(query)
    if required_intent and not any(term in haystack for term in required_intent):
        return False

    return True
