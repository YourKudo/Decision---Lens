from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import aiohttp

from relevance import is_relevant
from schema import Comment, Source, SourceMetrics


class YouTubeScraper:
    def __init__(self) -> None:
        self.base_url = "https://www.youtube.com"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (compatible; DecisionIntelligenceBot/1.0)",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "identity",
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
        search_url = f"{self.base_url}/results?search_query={quote_plus(query)}"

        try:
            html = await self._fetch_text(session, search_url)
            initial_data = self._extract_json_blob(html, "var ytInitialData = ")
            video_items = self._extract_video_items(initial_data)

            for item in video_items:
                video_id = item.get("videoId")
                if not video_id:
                    continue
                preview_title = self._runs_text(item.get("title", {}).get("runs", []))
                if not is_relevant(query, [preview_title]):
                    continue

                await asyncio.sleep(0.35)
                source = await self._scrape_video(session, video_id, item)
                if source and is_relevant(query, [source.title, source.content]):
                    sources.append(source)
                if len(sources) >= max_results:
                    break
        finally:
            if owned_session:
                await session.close()

        return sources

    async def _scrape_video(
        self,
        session: aiohttp.ClientSession,
        video_id: str,
        item: Dict[str, Any],
    ) -> Optional[Source]:
        url = f"{self.base_url}/watch?v={video_id}"
        html = await self._fetch_text(session, url)
        initial_data = self._extract_json_blob(html, "var ytInitialData = ")
        initial_player = self._extract_json_blob(html, "var ytInitialPlayerResponse = ")
        api_key = self._extract_string_value(html, "INNERTUBE_API_KEY")
        title = (
            initial_player.get("videoDetails", {}).get("title")
            or self._runs_text(item.get("title", {}).get("runs", []))
            or "YouTube video"
        )
        description = (
            initial_player.get("videoDetails", {}).get("shortDescription")
            or title
        )

        comments = []
        continuation = self._find_first_value(initial_data, "token")
        if continuation and api_key:
            comments = await self._fetch_comments(session, api_key, continuation)

        return Source(
            platform="youtube",
            title=title,
            url=url,
            content=description[:1600],
            comments=comments,
            metrics=SourceMetrics(
                likes=self._extract_like_count(initial_data),
                comments_count=self._extract_comment_count(initial_data),
            ),
        )

    async def _fetch_comments(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        continuation: str,
        limit: int = 8,
    ) -> List[Comment]:
        endpoint = f"{self.base_url}/youtubei/v1/next?key={api_key}"
        payload = {
            "context": {
                "client": {
                    "clientName": "WEB",
                    "clientVersion": "2.20240207.00.00",
                }
            },
            "continuation": continuation,
        }
        async with session.post(
            endpoint,
            headers=self.headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as response:
            if response.status >= 400:
                return []
            data = await response.json()

        nodes = self._collect_by_key(data, "commentRenderer")
        comments: List[Comment] = []
        for node in nodes:
            text = self._runs_text(node.get("contentText", {}).get("runs", []))
            if not text:
                continue
            comments.append(
                Comment(
                    text=text,
                    upvotes=self._parse_count_text(
                        node.get("voteCount", {}).get("simpleText")
                    ),
                    author=node.get("authorText", {}).get("simpleText"),
                )
            )
            if len(comments) >= limit:
                break
        return comments

    def _extract_video_items(self, initial_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for renderer in self._collect_by_key(initial_data, "videoRenderer"):
            items.append(renderer)
        return items

    def _extract_comment_count(self, data: Dict[str, Any]) -> Optional[int]:
        text = self._find_first_value(data, "countText")
        if isinstance(text, dict):
            return self._parse_count_text(text.get("simpleText"))
        if isinstance(text, str):
            return self._parse_count_text(text)
        return None

    def _extract_like_count(self, data: Dict[str, Any]) -> Optional[int]:
        labels = self._collect_by_key(data, "accessibilityData")
        for label in labels:
            text = label.get("label", "")
            if "like" in text.lower():
                value = self._parse_count_text(text)
                if value is not None:
                    return value
        return None

    def _parse_count_text(self, text: Optional[str]) -> Optional[int]:
        if not text:
            return None
        cleaned = text.replace(",", "").lower()
        match = re.search(r"(\d+(?:\.\d+)?)\s*([km]?)", cleaned)
        if not match:
            return None
        value = float(match.group(1))
        suffix = match.group(2)
        if suffix == "k":
            value *= 1_000
        elif suffix == "m":
            value *= 1_000_000
        return int(value)

    def _extract_json_blob(self, html: str, prefix: str) -> Dict[str, Any]:
        start = html.find(prefix)
        if start == -1:
            return {}
        start = html.find("{", start)
        if start == -1:
            return {}

        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(html)):
            char = html[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(html[start : index + 1])
                    except json.JSONDecodeError:
                        return {}
        return {}

    def _extract_string_value(self, html: str, key: str) -> Optional[str]:
        match = re.search(rf'"{re.escape(key)}":"([^"]+)"', html)
        if match:
            return match.group(1)
        return None

    def _find_first_value(self, obj: Any, key: str) -> Any:
        if isinstance(obj, dict):
            if key in obj:
                return obj[key]
            for value in obj.values():
                found = self._find_first_value(value, key)
                if found is not None:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = self._find_first_value(item, key)
                if found is not None:
                    return found
        return None

    def _collect_by_key(self, obj: Any, key: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        if isinstance(obj, dict):
            for current_key, value in obj.items():
                if current_key == key and isinstance(value, dict):
                    results.append(value)
                else:
                    results.extend(self._collect_by_key(value, key))
        elif isinstance(obj, list):
            for item in obj:
                results.extend(self._collect_by_key(item, key))
        return results

    def _runs_text(self, runs: List[Dict[str, Any]]) -> str:
        return "".join(run.get("text", "") for run in runs).strip()

    async def _fetch_text(self, session: aiohttp.ClientSession, url: str) -> str:
        async with session.get(
            url,
            headers=self.headers,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as response:
            response.raise_for_status()
            return await response.text()
