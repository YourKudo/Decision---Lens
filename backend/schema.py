from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class Comment(BaseModel):
    text: str
    upvotes: Optional[int] = None
    author: Optional[str] = None


class SourceMetrics(BaseModel):
    likes: Optional[int] = None
    comments_count: Optional[int] = None
    score: Optional[int] = None


class Source(BaseModel):
    platform: Literal["reddit", "youtube", "quora"]
    title: str = ""
    url: Optional[str] = None
    content: str
    comments: List[Comment] = Field(default_factory=list)
    metrics: Optional[SourceMetrics] = None


class ScrapeFailure(BaseModel):
    platform: str
    error: str


class RawData(BaseModel):
    query: str
    sources: List[Source] = Field(default_factory=list)
    failures: List[ScrapeFailure] = Field(default_factory=list)


class Opinion(BaseModel):
    source: str
    sentiment: Literal["positive", "negative", "neutral", "mixed"]
    reason: List[str] = Field(default_factory=list)
    stance: Literal["buy", "not_buy", "wait", "mixed", "unknown"]
    weight: float = 0.5
    evidence: str
    source_url: Optional[str] = None


class Aggregated(BaseModel):
    pros: List[str] = Field(default_factory=list)
    cons: List[str] = Field(default_factory=list)
    neutral_points: List[str] = Field(default_factory=list)
    conflicting_opinions: List[str] = Field(default_factory=list)


class ProcessedData(BaseModel):
    decision_topic: str
    options: List[str] = Field(default_factory=lambda: ["buy", "not buy", "wait"])
    opinions: List[Opinion] = Field(default_factory=list)
    aggregated: Aggregated


class WhatPeopleSay(BaseModel):
    buy: int
    not_buy: int
    wait: int


class SourceDistribution(BaseModel):
    reddit: int = 0
    youtube: int = 0
    quora: int = 0


class SourceReference(BaseModel):
    platform: Literal["reddit", "youtube", "quora"]
    title: str
    url: Optional[str] = None
    snippet: str
    comments_analyzed: int = 0


class FinalResponse(BaseModel):
    decision_topic: str
    summary: str
    decision_score: int
    confidence: int
    pros: List[str] = Field(default_factory=list)
    cons: List[str] = Field(default_factory=list)
    what_people_say: WhatPeopleSay
    key_insights: List[str] = Field(default_factory=list)
    source_distribution: SourceDistribution
    sources_used: List[SourceReference] = Field(default_factory=list)
    normalized_data: RawData
    processed_data: ProcessedData
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AnalyzeRequest(BaseModel):
    query: str
    user_type: Optional[str] = None
    max_results_per_source: int = Field(default=6, ge=3, le=10)
    use_cache: bool = True


class StreamEvent(BaseModel):
    event: str
    message: str
    data: Optional[Dict[str, Any]] = None
