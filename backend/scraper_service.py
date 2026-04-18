from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Dict, List, Tuple

import aiohttp

from quora_scraper import QuoraScraper
from reddit_scraper import RedditScraper
from schema import RawData, ScrapeFailure, Source
from youtube_scraper import YouTubeScraper


class TTLCache:
    def __init__(self, ttl_seconds: int = 900) -> None:
        self.ttl_seconds = ttl_seconds
        self._store: Dict[str, Tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        cached = self._store.get(key)
        if not cached:
            return None
        expires_at, value = cached
        if expires_at < time.time():
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (time.time() + self.ttl_seconds, value)


class ScraperService:
    def __init__(self) -> None:
        self.reddit_scraper = RedditScraper()
        self.youtube_scraper = YouTubeScraper()
        self.quora_scraper = QuoraScraper()
        self.cache = TTLCache(ttl_seconds=900)

    async def scrape_all(
        self,
        query: str,
        max_results_per_source: int = 6,
        use_cache: bool = True,
    ) -> RawData:
        cache_key = f"{query.lower().strip()}::{max_results_per_source}"
        if use_cache:
            cached = self.cache.get(cache_key)
            if cached:
                return cached

        async with aiohttp.ClientSession() as session:
            tasks = [
                self._run_scraper(
                    "reddit",
                    self.reddit_scraper.scrape(
                        query,
                        max_results=max_results_per_source,
                        session=session,
                    ),
                ),
                self._run_scraper(
                    "youtube",
                    self.youtube_scraper.scrape(
                        query,
                        max_results=max_results_per_source,
                        session=session,
                    ),
                ),
                self._run_scraper(
                    "quora",
                    self.quora_scraper.scrape(
                        query,
                        max_results=max_results_per_source,
                        session=session,
                    ),
                ),
            ]
            results = await asyncio.gather(*tasks)

        sources: List[Source] = []
        failures: List[ScrapeFailure] = []
        for platform, payload, error in results:
            sources.extend(payload)
            if error:
                failures.append(ScrapeFailure(platform=platform, error=error))

        raw_data = RawData(query=query, sources=sources, failures=failures)
        if use_cache:
            self.cache.set(cache_key, raw_data)
        return raw_data

    async def _run_scraper(
        self,
        platform: str,
        coro: Awaitable[List[Source]],
    ) -> Tuple[str, List[Source], str | None]:
        try:
            result = await coro
            return platform, result, None
        except Exception as exc:
            return platform, [], str(exc)
