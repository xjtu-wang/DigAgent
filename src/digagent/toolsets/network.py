from __future__ import annotations

import json
import re
from xml.etree import ElementTree as ET
from html import unescape
from typing import Any

import httpx

from digagent.config import AppSettings

TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
HREF_RE = re.compile(r"""href=["']([^"']+)["']""", re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")
SITE_ONLY_RE = re.compile(r"^site:(?P<host>[^\s/]+)$", re.IGNORECASE)


class NetworkToolset:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    async def web_fetch(self, arguments: dict[str, Any]) -> tuple[str, str, str, list[dict[str, Any]], dict[str, Any], str, str]:
        url = str(arguments["url"])
        method = str(arguments.get("method", "GET")).upper()
        timeout = float(arguments.get("timeout") or 15.0)
        if method not in {"GET", "HEAD"}:
            raise ValueError(f"web_fetch only supports GET/HEAD, got {method}")
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
                response = await client.request(method, url)
        except httpx.TransportError as exc:
            facts = [
                {"key": "url", "value": url},
                {"key": "error", "value": type(exc).__name__},
                {"key": "error_message", "value": str(exc)},
                {"key": "transport_error", "value": True},
                {"key": "reachable", "value": False},
            ]
            payload = {"url": url, "error": type(exc).__name__, "message": str(exc), "reachable": False}
            summary = f"web_fetch {url} failed: {type(exc).__name__}: {exc} [TRANSPORT_ERROR]"
            source = {"tool_name": "web_fetch", "url": url, "error": type(exc).__name__}
            return f"Web Fetch Error: {url}", summary, json.dumps(payload, ensure_ascii=False, indent=2), facts, source, "application/json", "file"
        text = response.text[:5000]
        title = self._extract_title(text, fallback=url)
        links = HREF_RE.findall(text)
        redirect_chain = [str(r.url) for r in response.history]
        error_status = response.status_code >= 400
        facts = self._fetch_facts(response.status_code, response.headers.get("content-type", ""), title, len(links))
        facts.append({"key": "redirect_chain", "value": redirect_chain})
        facts.append({"key": "error_status", "value": error_status})
        facts.append({"key": "reachable", "value": True})
        if error_status:
            facts.append({"key": "http_error", "value": True})
        payload = {
            "url": str(response.url),
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "title": title,
            "links": links[:20],
            "body_excerpt": text,
            "redirect_chain": redirect_chain,
            "reachable": True,
            "error_status": error_status,
        }
        status_note = " [HTTP_ERROR]" if error_status else ""
        summary = f"Fetched {url} with status {response.status_code} and extracted {len(links)} links.{status_note}"
        return f"Web Fetch: {url}", summary, json.dumps(payload, ensure_ascii=False, indent=2), facts, {"tool_name": "web_fetch", "url": str(response.url)}, "application/json", "html"

    async def web_search(self, arguments: dict[str, Any]) -> tuple[str, str, str, list[dict[str, Any]], dict[str, Any], str, str]:
        query = str(arguments.get("query") or "").strip()
        if not query:
            raise ValueError("web_search requires a non-empty query")
        limit = int(arguments.get("limit") or 5)
        effective_query = self._normalize_search_query(query)
        provider_ok, provider_usable, provider_error, results = await self._bing_search(effective_query, limit)
        empty_result = len(results) == 0
        facts: list[dict[str, Any]] = [
            {"key": "match_count", "value": len(results)},
            {"key": "query", "value": query},
            {"key": "effective_query", "value": effective_query},
            {"key": "empty_result", "value": empty_result},
            {"key": "provider_reachable", "value": provider_ok},
            {"key": "provider_usable", "value": provider_usable},
        ]
        if provider_error:
            facts.append({"key": "provider_error", "value": provider_error})
        marker = " [NO_RESULTS]" if empty_result else ""
        provider_note = ""
        if provider_error and not provider_ok:
            provider_note = f" (provider unreachable: {provider_error})"
        elif provider_error and not provider_usable:
            provider_note = f" (provider unusable: {provider_error})"
        summary = f"Web search returned {len(results)} results for query '{query}'.{marker}{provider_note}"
        source: dict[str, Any] = {
            "tool_name": "web_search",
            "provider": self.settings.web_search_base_url,
            "provider_name": "bing_rss",
            "provider_usable": provider_usable,
            "degraded": empty_result or not provider_ok or not provider_usable,
        }
        payload = {
            "results": results,
            "query": query,
            "effective_query": effective_query,
            "empty_result": empty_result,
            "provider_reachable": provider_ok,
            "provider_usable": provider_usable,
        }
        return "Web Search Results", summary, json.dumps(payload, ensure_ascii=False, indent=2), facts, source, "application/json", "file"

    async def _bing_search(self, query: str, limit: int) -> tuple[bool, bool, str | None, list[dict[str, str]]]:
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
                response = await client.get(self.settings.web_search_base_url, params={"q": query, "format": "rss"})
        except httpx.TransportError as exc:
            return False, False, f"{type(exc).__name__}: {exc}", []
        if response.status_code >= 400:
            return True, False, f"HTTP {response.status_code}", []
        content_type = response.headers.get("content-type", "").lower()
        if "xml" not in content_type:
            return True, False, f"unexpected content-type: {content_type or 'missing'}", []
        try:
            return True, True, None, self._parse_bing_rss(response.text, limit)
        except ET.ParseError as exc:
            return True, False, f"invalid xml: {exc}", []

    def _parse_bing_rss(self, xml_text: str, limit: int) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        seen: set[str] = set()
        root = ET.fromstring(xml_text)
        for item in root.findall(".//item"):
            if len(results) >= limit:
                break
            title = unescape(TAG_RE.sub("", item.findtext("title") or "").strip())
            url = unescape((item.findtext("link") or "").strip())
            if not title or not url or url in seen:
                continue
            seen.add(url)
            results.append({"title": title, "url": url})
        return results

    def _normalize_search_query(self, query: str) -> str:
        match = SITE_ONLY_RE.fullmatch(query)
        if not match:
            return query
        host = match.group("host").strip()
        return f"{query} {host}"

    def _extract_title(self, text: str, *, fallback: str) -> str:
        title_match = TITLE_RE.search(text)
        return unescape(title_match.group(1).strip()) if title_match else fallback

    def _fetch_facts(self, status_code: int, content_type: str, title: str, link_count: int) -> list[dict[str, Any]]:
        return [
            {"key": "status_code", "value": status_code},
            {"key": "content_type", "value": content_type},
            {"key": "title", "value": title},
            {"key": "link_count", "value": link_count},
        ]
