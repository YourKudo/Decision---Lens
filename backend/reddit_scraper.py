from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import aiohttp

from relevance import is_relevant
from schema import Comment, Source, SourceMetrics


class RedditScraper:
    def __init__(self) -> None:
        self.base_url = "https://www.reddit.com"
        self.headers = {
            "User-Agent": "DecisionIntelligenceBot/1.0",
            "Accept": "application/json",
        }

    async def scrape(
        self,
        query: str,
        max_results: int = 6,
        session: Optional[aiohttp.ClientSession] = None,
    ) -> List[Source]:
        search_url = (
            f"{self.base_url}/search.json?q={quote_plus(query)}&sort=relevance"
            f"&limit={min(max_results * 5, 25)}&type=link"
        )
        owned_session = session is None
        session = session or aiohttp.ClientSession(headers=self.headers)
        sources: List[Source] = []

        try:
            payload = await self._fetch_json(session, search_url)
            posts = payload.get("data", {}).get("children", [])
            for post in posts:
                data = post.get("data", {})
                permalink = data.get("permalink")
                if not permalink:
                    continue

                title = data.get("title", "")
                body = data.get("selftext") or title or ""
                if not is_relevant(query, [title, body]):
                    continue

                await asyncio.sleep(0.2)
                comments = await self._fetch_comments(session, permalink)
                sources.append(
                    Source(
                        platform="reddit",
                        title=title,
                        url=f"{self.base_url}{permalink}",
                        content=body.strip(),
                        comments=comments,
                        metrics=SourceMetrics(
                            score=data.get("score"),
                            comments_count=data.get("num_comments"),
                        ),
                    )
                )
                if len(sources) >= max_results:
                    break
        finally:
            if owned_session:
                await session.close()

        return sources

    async def _fetch_comments(
        self,
        session: aiohttp.ClientSession,
        permalink: str,
        limit: int = 8,
    ) -> List[Comment]:
        comments_url = f"{self.base_url}{permalink}.json?limit={limit}&sort=top"
        listing = await self._fetch_json(session, comments_url)
        if not isinstance(listing, list) or len(listing) < 2:
            return []

        comment_nodes = listing[1].get("data", {}).get("children", [])
        comments: List[Comment] = []
        for node in comment_nodes:
            data = node.get("data", {})
            text = (data.get("body") or "").strip()
            author = data.get("author")
            if not text:
                continue
            if author and author.lower().startswith("auto"):
                continue
            if "i am a bot" in text.lower():
                continue
            comments.append(
                Comment(
                    text=text,
                    upvotes=data.get("ups"),
                    author=author,
                )
            )
            if len(comments) >= limit:
                break
        return comments

    async def _fetch_json(
        self,
        session: aiohttp.ClientSession,
        url: str,
    ) -> Dict[str, Any] | List[Any]:
        async with session.get(
            url,
            headers=self.headers,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as response:
            response.raise_for_status()
            return await response.json()
