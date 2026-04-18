from __future__ import annotations

import asyncio
import re
from html import unescape
from typing import List, Optional
from urllib.parse import quote_plus

import aiohttp
from bs4 import BeautifulSoup

from relevance import is_relevant
from schema import Comment, Source


class QuoraScraper:
    def __init__(self) -> None:
        self.headers = {
            "User-Agent": "Mozilla/5.0 (compatible; DecisionIntelligenceBot/1.0)",
        }

    async def scrape(
        self,
        query: str,
        max_results: int = 6,
        session: Optional[aiohttp.ClientSession] = None,
    ) -> List[Source]:
        owned_session = session is None
        session = session or aiohttp.ClientSession(headers=self.headers)
        sources: List[Source] = []
        search_url = (
            "https://html.duckduckgo.com/html/"
            f"?q={quote_plus(f'site:quora.com {query}')}"
        )

        try:
            search_html = await self._fetch_text(session, search_url)
            question_urls = self._extract_quora_links(search_html)[:max_results]
            for url in question_urls:
                await asyncio.sleep(0.35)
                source = await self._scrape_question(session, url)
                if source and is_relevant(query, [source.title, source.content]):
                    sources.append(source)
        finally:
            if owned_session:
                await session.close()

        return sources

    async def _scrape_question(
        self,
        session: aiohttp.ClientSession,
        url: str,
    ) -> Optional[Source]:
        html = await self._fetch_text(session, url)
        soup = BeautifulSoup(html, "html.parser")
        title = self._first_text(
            soup,
            ["h1", "title", "div.q-text.qu-dynamicFontSize--large"],
        )
        answer_nodes = soup.select(
            "div.q-box.qu-wordBreak--break-word, div[data-testid='answer_content']"
        )

        comments: List[Comment] = []
        for node in answer_nodes:
            text = " ".join(node.stripped_strings)
            if len(text) < 80:
                continue
            comments.append(
                Comment(
                    text=text[:1200],
                    upvotes=self._extract_upvotes(node.get_text(" ", strip=True)),
                )
            )
            if len(comments) >= 8:
                break

        if not title and not comments:
            return None

        content = title or "Relevant Quora discussion"
        return Source(
            platform="quora",
            title=title or "Quora discussion",
            url=url,
            content=content,
            comments=comments,
        )

    def _extract_quora_links(self, html: str) -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        urls: List[str] = []
        for anchor in soup.select("a.result__a"):
            href = anchor.get("href")
            if href and "quora.com" in href and href not in urls:
                urls.append(href)
        return urls

    def _extract_upvotes(self, text: str) -> Optional[int]:
        match = re.search(r"(\d[\d,]*)\s+upvote", text, re.IGNORECASE)
        if not match:
            return None
        return int(match.group(1).replace(",", ""))

    def _first_text(self, soup: BeautifulSoup, selectors: List[str]) -> str:
        for selector in selectors:
            node = soup.select_one(selector)
            if node:
                return unescape(" ".join(node.stripped_strings))
        return ""

    async def _fetch_text(self, session: aiohttp.ClientSession, url: str) -> str:
        async with session.get(
            url,
            headers=self.headers,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as response:
            response.raise_for_status()
            return await response.text()
