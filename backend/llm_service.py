from __future__ import annotations

import asyncio
import json
import os
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Type, TypeVar

import aiohttp
from pydantic import BaseModel, Field, ValidationError

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

from relevance import extract_keywords, is_relevant
from schema import (
    Aggregated,
    FinalResponse,
    Opinion,
    ProcessedData,
    RawData,
    SourceDistribution,
    SourceReference,
    WhatPeopleSay,
)

if load_dotenv:
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

T = TypeVar("T", bound=BaseModel)


class OpinionExtractionResult(BaseModel):
    sentiment: str
    reasons: List[str] = Field(default_factory=list)
    stance: str
    weight: float
    relevant: bool = True


class AggregationResult(BaseModel):
    pros: List[str] = Field(default_factory=list)
    cons: List[str] = Field(default_factory=list)
    neutral_points: List[str] = Field(default_factory=list)
    conflicting_opinions: List[str] = Field(default_factory=list)


class SummaryResult(BaseModel):
    summary: str


class LLMService:
    def __init__(self) -> None:
        self.base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
        self.model = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
        self.ollama_configured = bool(self.base_url and self.model)
        self._semaphore = asyncio.Semaphore(3)
        self._timeout = aiohttp.ClientTimeout(total=75)

    async def extract_opinions(self, raw_data: RawData) -> List[Opinion]:
        documents = self._build_documents(raw_data)
        tasks = [self._extract_single_opinion(document) for document in documents]
        opinions = await asyncio.gather(*tasks)
        return [opinion for opinion in opinions if opinion is not None]

    async def aggregate(self, opinions: List[Opinion], topic: str) -> Aggregated:
        if self.ollama_configured and opinions:
            aggregated = await self._aggregate_with_llm(opinions, topic)
            if aggregated:
                return aggregated
        return self._aggregate_with_rules(opinions)

    async def generate_final_response(
        self,
        processed: ProcessedData,
        raw_data: RawData,
    ) -> FinalResponse:
        what_people_say = self._calculate_stance_distribution(processed.opinions)
        decision_score = self._calculate_decision_score(processed.opinions)
        confidence = self._calculate_confidence(raw_data, processed.opinions)
        summary = await self._generate_summary(
            processed.decision_topic,
            processed.aggregated,
            what_people_say,
            decision_score,
        )
        key_insights = self._build_key_insights(processed.aggregated, what_people_say)
        source_distribution = self._source_distribution(raw_data)
        sources_used = self._build_source_references(raw_data)

        return FinalResponse(
            decision_topic=processed.decision_topic,
            summary=summary,
            decision_score=decision_score,
            confidence=confidence,
            pros=processed.aggregated.pros,
            cons=processed.aggregated.cons,
            what_people_say=what_people_say,
            key_insights=key_insights,
            source_distribution=source_distribution,
            sources_used=sources_used,
            normalized_data=raw_data,
            processed_data=processed,
            metadata={
                "sources_scraped": len(raw_data.sources),
                "failures": [failure.model_dump() for failure in raw_data.failures],
                "llm_enabled": self.ollama_configured,
                "llm_provider": "ollama",
                "llm_model": self.model,
            },
        )

    async def _extract_single_opinion(self, document: Dict[str, Any]) -> Optional[Opinion]:
        if self.ollama_configured:
            llm_result = await self._extract_with_llm(document)
            if llm_result:
                return llm_result
        return self._extract_with_rules(document)

    async def _extract_with_llm(self, document: Dict[str, Any]) -> Optional[Opinion]:
        if not self._is_document_relevant(document["topic"], document["text"]):
            return None

        messages = [
            {
                "role": "system",
                "content": (
                    "You extract decision-making opinions from public web discussions. "
                    "Ignore repost boilerplate, moderation text, and off-topic mentions. "
                    "Return short normalized reasons only, like high price, better battery life, "
                    "incremental upgrade, strong ecosystem, better alternatives available, "
                    "worth upgrading now, or worth waiting for next model."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Decision topic: {document['topic']}\n"
                    f"Platform: {document['platform']}\n"
                    "Analyze this text and return JSON with keys "
                    "sentiment, reasons, stance, weight, relevant.\n\n"
                    f"{document['text'][:2200]}"
                ),
            },
        ]
        parsed = await self._chat_json(messages, OpinionExtractionResult)
        if not parsed or not parsed.relevant:
            return None

        return Opinion(
            source=document["platform"],
            sentiment=self._safe_sentiment(parsed.sentiment),
            reason=self._normalize_reason_list(parsed.reasons),
            stance=self._safe_stance(parsed.stance),
            weight=self._safe_weight(parsed.weight),
            evidence=document["text"][:400],
            source_url=document.get("source_url"),
        )

    def _extract_with_rules(self, document: Dict[str, Any]) -> Opinion:
        text = document["text"].lower()
        reasons = self._extract_reason_themes(document["text"])

        sentiment = "neutral"
        if any(reason in reasons for reason in {"worth upgrading now", "better battery life", "better performance", "strong ecosystem"}):
            sentiment = "positive"
        if any(reason in reasons for reason in {"high price", "worth waiting for next model", "better alternatives available", "incremental upgrade"}):
            sentiment = "negative" if sentiment == "neutral" else "mixed"

        stance = "unknown"
        if "don't buy" in text or "do not buy" in text or "avoid" in text:
            stance = "not_buy"
        elif "wait" in text or "hold off" in text:
            stance = "wait"
        elif "worth it" in text or "buy now" in text or "upgrade now" in text:
            stance = "buy"
        elif sentiment == "positive":
            stance = "buy"
        elif sentiment == "negative" and "wait" in " ".join(reasons):
            stance = "wait"

        return Opinion(
            source=document["platform"],
            sentiment=self._safe_sentiment(sentiment),
            reason=reasons[:4],
            stance=self._safe_stance(stance),
            weight=min(1.0, 0.48 + 0.08 * len(reasons)),
            evidence=document["text"][:400],
            source_url=document.get("source_url"),
        )

    async def _aggregate_with_llm(self, opinions: List[Opinion], topic: str) -> Optional[Aggregated]:
        messages = [
            {
                "role": "system",
                "content": (
                    "Aggregate opinions into concise pros and cons for a decision. "
                    "Never copy long sentences. Prefer reusable 2-5 word reason labels."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Decision topic: {topic}\n"
                    "Return JSON with pros, cons, neutral_points, conflicting_opinions.\n"
                    f"Opinions: {json.dumps([op.model_dump() for op in opinions], ensure_ascii=True)[:10000]}"
                ),
            },
        ]
        parsed = await self._chat_json(messages, AggregationResult)
        if not parsed:
            return None

        return Aggregated(
            pros=self._normalize_reason_list(parsed.pros)[:8],
            cons=self._normalize_reason_list(parsed.cons)[:8],
            neutral_points=self._normalize_reason_list(parsed.neutral_points)[:6],
            conflicting_opinions=self._normalize_reason_list(parsed.conflicting_opinions)[:4],
        )

    def _aggregate_with_rules(self, opinions: List[Opinion]) -> Aggregated:
        pros = Counter()
        cons = Counter()
        neutral = Counter()

        for opinion in opinions:
            for reason in opinion.reason:
                if not reason:
                    continue
                bucket_name = self._reason_bucket(reason, opinion.sentiment)
                bucket = neutral
                if bucket_name == "pros":
                    bucket = pros
                elif bucket_name == "cons":
                    bucket = cons
                bucket[reason] += 1

        conflicting = []
        if pros and cons:
            conflicting.append("People are split between buying now and waiting for the next model cycle.")

        return Aggregated(
            pros=[item for item, _ in pros.most_common(8)],
            cons=[item for item, _ in cons.most_common(8)],
            neutral_points=[item for item, _ in neutral.most_common(6)],
            conflicting_opinions=conflicting,
        )

    async def _generate_summary(
        self,
        topic: str,
        aggregated: Aggregated,
        what_people_say: WhatPeopleSay,
        decision_score: int,
    ) -> str:
        if self.ollama_configured:
            messages = [
                {
                    "role": "system",
                    "content": "Write a concise 2-3 sentence decision summary. Mention the main trade-off and do not invent facts.",
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "topic": topic,
                            "pros": aggregated.pros,
                            "cons": aggregated.cons,
                            "neutral_points": aggregated.neutral_points,
                            "what_people_say": what_people_say.model_dump(),
                            "decision_score": decision_score,
                        },
                        ensure_ascii=True,
                    ),
                },
            ]
            parsed = await self._chat_json(messages, SummaryResult)
            if parsed and parsed.summary.strip():
                return parsed.summary.strip()

        leaning = "leans toward buying" if decision_score >= 60 else "leans toward waiting"
        pros = ", ".join(aggregated.pros[:2]) or "the upside"
        cons = ", ".join(aggregated.cons[:2]) or "the trade-offs"
        return (
            f"Public opinion on {topic} {leaning}. "
            f"The strongest positives are {pros}, while the biggest concerns are {cons}."
        )

    async def _chat_json(self, messages: List[Dict[str, str]], schema: Type[T]) -> Optional[T]:
        async with self._semaphore:
            try:
                async with aiohttp.ClientSession(timeout=self._timeout) as session:
                    async with session.post(
                        f"{self.base_url}/api/chat",
                        json={
                            "model": self.model,
                            "messages": messages,
                            "stream": False,
                            "format": "json",
                            "options": {"temperature": 0.1},
                        },
                    ) as response:
                        response.raise_for_status()
                        payload = await response.json()
            except Exception:
                return None

        content = payload.get("message", {}).get("content") or payload.get("response") or ""
        data = self._extract_json(content)
        if not isinstance(data, dict):
            return None

        try:
            return schema.model_validate(data)
        except ValidationError:
            return None

    def _calculate_stance_distribution(self, opinions: List[Opinion]) -> WhatPeopleSay:
        scores = {"buy": 0.0, "not_buy": 0.0, "wait": 0.0}
        for opinion in opinions:
            if opinion.stance in scores:
                scores[opinion.stance] += max(opinion.weight, 0.1)
        total = sum(scores.values()) or 1.0
        return WhatPeopleSay(
            buy=round(scores["buy"] / total * 100),
            not_buy=round(scores["not_buy"] / total * 100),
            wait=round(scores["wait"] / total * 100),
        )

    def _calculate_decision_score(self, opinions: List[Opinion]) -> int:
        if not opinions:
            return 50
        score = 50.0
        for opinion in opinions:
            if opinion.stance == "buy":
                score += 11 * opinion.weight
            elif opinion.stance == "not_buy":
                score -= 11 * opinion.weight
            elif opinion.stance == "wait":
                score -= 5 * opinion.weight

            if opinion.sentiment == "positive":
                score += 5 * opinion.weight
            elif opinion.sentiment == "negative":
                score -= 5 * opinion.weight
            elif opinion.sentiment == "mixed":
                score -= 1.0 * opinion.weight

        return max(0, min(100, round(score)))

    def _calculate_confidence(self, raw_data: RawData, opinions: List[Opinion]) -> int:
        base = min(50 + len(raw_data.sources) * 4 + len(opinions), 92)
        penalty = min(len(raw_data.failures) * 10, 30)
        return max(20, min(100, base - penalty))

    def _build_key_insights(self, aggregated: Aggregated, what_people_say: WhatPeopleSay) -> List[str]:
        insights: List[str] = []
        if aggregated.pros:
            insights.append(f"Most repeated upside: {aggregated.pros[0]}.")
        if aggregated.cons:
            insights.append(f"Most repeated concern: {aggregated.cons[0]}.")
        insights.append(
            f"Opinion split is Buy {what_people_say.buy}%, Wait {what_people_say.wait}%, Not buy {what_people_say.not_buy}%."
        )
        insights.extend(aggregated.conflicting_opinions[:2])
        return insights[:5]

    def _source_distribution(self, raw_data: RawData) -> SourceDistribution:
        counts = Counter(source.platform for source in raw_data.sources)
        return SourceDistribution(
            reddit=counts.get("reddit", 0),
            youtube=counts.get("youtube", 0),
            quora=counts.get("quora", 0),
        )

    def _build_source_references(self, raw_data: RawData) -> List[SourceReference]:
        references: List[SourceReference] = []
        for source in raw_data.sources[:8]:
            preferred_comment = next(
                (
                    comment.text
                    for comment in source.comments
                    if comment.text.strip()
                    and "i am a bot" not in comment.text.lower()
                    and not (comment.author or "").lower().startswith("auto")
                ),
                None,
            )
            snippet_source = preferred_comment or source.content
            snippet = re.sub(r"\s+", " ", snippet_source).strip()[:180]
            references.append(
                SourceReference(
                    platform=source.platform,
                    title=source.title or "Untitled discussion",
                    url=source.url,
                    snippet=snippet,
                    comments_analyzed=len(source.comments),
                )
            )
        return references

    def _build_documents(self, raw_data: RawData) -> List[Dict[str, Any]]:
        documents: List[Dict[str, Any]] = []
        for source in raw_data.sources:
            base = {
                "platform": source.platform,
                "topic": raw_data.query,
                "source_url": source.url,
            }
            source_text = f"{source.title}\n{source.content}".strip()
            if (
                source_text
                and source.content.strip() != source.title.strip()
                and self._is_document_relevant(raw_data.query, source_text)
            ):
                documents.append({**base, "text": source_text})
            for comment in source.comments[:4]:
                if comment.text.strip() and self._is_document_relevant(raw_data.query, comment.text.strip()):
                    documents.append({**base, "text": comment.text.strip()})
        return documents[:24]

    def _extract_reason_themes(self, text: str) -> List[str]:
        lower = text.lower()
        theme_map = [
            ("better battery life", ["battery life", "battery", "battery health"]),
            ("better performance", ["fast", "smooth", "performance"]),
            ("high price", ["expensive", "overpriced", "price", "cost", "emi", "afford"]),
            ("worth waiting for next model", ["wait", "hold off", "next year", "later"]),
            ("worth upgrading now", ["worth it", "upgrade asap", "buy now", "go for it"]),
            ("incremental upgrade", ["incremental", "minor upgrade", "refined upgrade"]),
            ("strong ecosystem", ["ecosystem"]),
            ("better alternatives available", ["other phones", "better specs", "mid-range", "alternative"]),
            ("camera improvement", ["camera"]),
        ]
        reasons = [label for label, needles in theme_map if any(needle in lower for needle in needles)]
        return reasons[:5] or ["unclear reasoning"]

    def _extract_json(self, text: str) -> Any:
        if not text:
            return None
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

    def _normalize_reason_list(self, reasons: List[str]) -> List[str]:
        normalized: List[str] = []
        seen = set()
        for reason in reasons:
            cleaned = re.sub(r"\s+", " ", str(reason)).strip(" -.:,")
            cleaned = cleaned[:80]
            if not cleaned:
                continue
            lowered = cleaned.lower()
            if lowered in seen or "unclear reasoning" in lowered:
                continue
            seen.add(lowered)
            normalized.append(cleaned)
        return normalized

    def _safe_sentiment(self, value: Any) -> str:
        value = str(value or "neutral").strip().lower()
        if value in {"positive", "negative", "neutral", "mixed"}:
            return value
        return "neutral"

    def _safe_stance(self, value: Any) -> str:
        value = str(value or "unknown").strip().lower().replace(" ", "_")
        if value in {"buy", "not_buy", "wait", "mixed", "unknown"}:
            return value
        if value in {"not-buy", "dont_buy"}:
            return "not_buy"
        return "unknown"

    def _safe_weight(self, value: Any) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.55

    def _is_document_relevant(self, topic: str, text: str) -> bool:
        cleaned = re.sub(r"\[[^\]]+\]\([^)]+\)", " ", text)
        lowered = cleaned.lower()
        if "i am not the oop" in lowered or "originally posted to" in lowered:
            return False
        return is_relevant(topic, [cleaned], min_score=0.34 if extract_keywords(topic) else 0.2)

    def _reason_bucket(self, reason: str, sentiment: str) -> str:
        lower = reason.lower()
        if lower in {"high price", "worth waiting for next model", "incremental upgrade", "better alternatives available"}:
            return "cons"
        if lower in {"better battery life", "better performance", "worth upgrading now", "strong ecosystem", "camera improvement"}:
            return "pros"
        if sentiment == "positive":
            return "pros"
        if sentiment == "negative":
            return "cons"
        return "neutral"
