from __future__ import annotations

import json
import time
from typing import Any, AsyncGenerator, Dict, Tuple

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from decision_engine import DecisionEngine
from llm_service import LLMService
from schema import AnalyzeRequest, FinalResponse, StreamEvent
from scraper_service import ScraperService

app = FastAPI(title="Decision Intelligence Chatbot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

scraper = ScraperService()
llm = LLMService()
engine = DecisionEngine(llm)

_response_cache: Dict[str, Tuple[float, FinalResponse]] = {}
_response_ttl = 900


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "llm_configured": llm.ollama_configured,
        "llm_provider": "ollama",
        "model": llm.model,
    }


@app.post("/analyze", response_model=FinalResponse)
async def analyze(request: AnalyzeRequest) -> FinalResponse:
    cached = _get_cached_response(request)
    if cached:
        return cached

    raw_data = await scraper.scrape_all(
        request.query,
        max_results_per_source=request.max_results_per_source,
        use_cache=request.use_cache,
    )
    processed = await engine.process(raw_data)
    response = await llm.generate_final_response(processed, raw_data)
    if request.use_cache:
        _set_cached_response(request, response)
    return response


@app.post("/analyze/stream")
async def analyze_stream(request: AnalyzeRequest) -> StreamingResponse:
    async def event_generator() -> AsyncGenerator[str, None]:
        cached = _get_cached_response(request)
        if cached:
            yield _sse(
                StreamEvent(
                    event="cached",
                    message="Returned cached analysis.",
                    data={"final": cached.model_dump()},
                )
            )
            yield _sse(StreamEvent(event="done", message="Analysis complete."))
            return

        yield _sse(
            StreamEvent(
                event="progress",
                message="Scraping Reddit, YouTube, and Quora discussions.",
            )
        )
        raw_data = await scraper.scrape_all(
            request.query,
            max_results_per_source=request.max_results_per_source,
            use_cache=request.use_cache,
        )

        yield _sse(
            StreamEvent(
                event="scraped",
                message=f"Collected {len(raw_data.sources)} source documents.",
                data={
                    "source_distribution": {
                        "reddit": len([s for s in raw_data.sources if s.platform == "reddit"]),
                        "youtube": len([s for s in raw_data.sources if s.platform == "youtube"]),
                        "quora": len([s for s in raw_data.sources if s.platform == "quora"]),
                    },
                    "failures": [failure.model_dump() for failure in raw_data.failures],
                },
            )
        )

        yield _sse(
            StreamEvent(
                event="progress",
                message="Running multi-stage opinion extraction and aggregation.",
            )
        )
        processed = await engine.process(raw_data)

        yield _sse(
            StreamEvent(
                event="processed",
                message=f"Extracted {len(processed.opinions)} opinions.",
                data={
                    "pros_preview": processed.aggregated.pros[:3],
                    "cons_preview": processed.aggregated.cons[:3],
                },
            )
        )

        yield _sse(
            StreamEvent(
                event="progress",
                message="Generating the final recommendation and decision graph.",
            )
        )
        response = await llm.generate_final_response(processed, raw_data)
        if request.use_cache:
            _set_cached_response(request, response)

        yield _sse(
            StreamEvent(
                event="final",
                message="Final response ready.",
                data={"final": response.model_dump()},
            )
        )
        yield _sse(StreamEvent(event="done", message="Analysis complete."))

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def _cache_key(request: AnalyzeRequest) -> str:
    user_type = (request.user_type or "").strip().lower()
    return f"{request.query.strip().lower()}::{request.max_results_per_source}::{user_type}"


def _get_cached_response(request: AnalyzeRequest) -> FinalResponse | None:
    cached = _response_cache.get(_cache_key(request))
    if not cached:
        return None
    expires_at, response = cached
    if expires_at < time.time():
        _response_cache.pop(_cache_key(request), None)
        return None
    return response


def _set_cached_response(request: AnalyzeRequest, response: FinalResponse) -> None:
    _response_cache[_cache_key(request)] = (time.time() + _response_ttl, response)


def _sse(event: StreamEvent) -> str:
    return f"data: {json.dumps(event.model_dump(), ensure_ascii=True)}\n\n"
