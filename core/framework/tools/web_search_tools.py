from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from typing import Any, Callable, Protocol
from urllib.parse import parse_qs, quote_plus, unquote, urlencode, urlsplit
from urllib.request import Request, urlopen

from core.framework.tools.models import ToolDefinition
from core.framework.tools.registry import ToolRegistry


WebSearchFetcher = Callable[[str, float], str]


@dataclass(frozen=True)
class WebSearchResult:
    title: str
    url: str
    snippet: str = ""
    source: str = "duckduckgo"

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "source": self.source,
        }


class WebSearchProvider(Protocol):
    def search(
        self,
        *,
        query: str,
        limit: int,
        timeout_seconds: float,
    ) -> list[WebSearchResult]: ...


class DuckDuckGoHtmlSearchProvider:
    def __init__(
        self,
        *,
        endpoint: str = "https://html.duckduckgo.com/html/",
        allowed_domains: list[str] | None = None,
        fetcher: WebSearchFetcher | None = None,
        user_agent: str = "NewsRoomToolRuntime/1.0",
    ) -> None:
        self.endpoint = endpoint
        self.allowed_domains = _allowed_domains(
            allowed_domains or ["html.duckduckgo.com", "duckduckgo.com"]
        )
        self.fetcher = fetcher
        self.user_agent = user_agent

    def search(
        self,
        *,
        query: str,
        limit: int,
        timeout_seconds: float,
    ) -> list[WebSearchResult]:
        self._ensure_endpoint_allowed()
        url = _url_with_query(self.endpoint, {"q": query})
        html = self.fetcher(url, timeout_seconds) if self.fetcher else self._fetch(url, timeout_seconds)
        parser = _DuckDuckGoResultParser()
        parser.feed(html)
        return parser.results[:limit]

    def _fetch(self, url: str, timeout_seconds: float) -> str:
        request = Request(url, headers={"User-Agent": self.user_agent})
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read(500_000)
        return body.decode("utf-8", errors="replace")

    def _ensure_endpoint_allowed(self) -> None:
        parts = urlsplit(self.endpoint)
        scheme = parts.scheme.casefold()
        if scheme not in {"http", "https"}:
            raise ValueError(f"web.search endpoint must be http or https: {self.endpoint}")
        host = (parts.hostname or "").casefold()
        if any(host == domain or host.endswith(f".{domain}") for domain in self.allowed_domains):
            return
        raise ValueError(f"web.search endpoint host is not in allowed domains: {host}")


def register_web_search_tools(
    registry: ToolRegistry,
    *,
    provider: WebSearchProvider | None = None,
) -> None:
    search_provider = provider or DuckDuckGoHtmlSearchProvider()
    registry.register(
        ToolDefinition(
            name="web.search",
            description="Search the public web through a configured search provider.",
            input_schema={
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                    "timeout_seconds": {"type": "number"},
                },
                "additionalProperties": False,
            },
            side_effect="read_only",
            concurrency_safe=True,
            timeout_seconds=20.0,
            max_result_bytes=500_000,
        ),
        lambda args: _search_web(args, provider=search_provider),
    )


def _search_web(args: dict[str, Any], *, provider: WebSearchProvider) -> dict[str, Any]:
    query = str(args["query"]).strip()
    if not query:
        raise ValueError("query is required")
    limit = _limit(args.get("limit"))
    timeout_seconds = _timeout(args.get("timeout_seconds"))
    results = provider.search(query=query, limit=limit, timeout_seconds=timeout_seconds)
    return {
        "query": query,
        "result_count": len(results),
        "results": [result.to_dict() for result in results],
    }


class _DuckDuckGoResultParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[WebSearchResult] = []
        self._capture_link = False
        self._capture_snippet = False
        self._link_href = ""
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {name.casefold(): value or "" for name, value in attrs}
        classes = set(attr_map.get("class", "").split())
        if tag.casefold() == "a" and "result__a" in classes:
            self._capture_link = True
            self._link_href = attr_map.get("href", "")
            self._text_parts = []
            return
        if "result__snippet" in classes:
            self._capture_snippet = True
            self._text_parts = []

    def handle_endtag(self, tag: str) -> None:
        if self._capture_link and tag.casefold() == "a":
            title = _collapse_text("".join(self._text_parts))
            url = _normalize_result_url(self._link_href)
            if title and url:
                self.results.append(WebSearchResult(title=title, url=url))
            self._capture_link = False
            self._link_href = ""
            self._text_parts = []
            return
        if self._capture_snippet and tag.casefold() in {"a", "div", "td"}:
            snippet = _collapse_text("".join(self._text_parts))
            if snippet and self.results:
                last = self.results[-1]
                if not last.snippet:
                    self.results[-1] = WebSearchResult(
                        title=last.title,
                        url=last.url,
                        snippet=snippet,
                        source=last.source,
                    )
            self._capture_snippet = False
            self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._capture_link or self._capture_snippet:
            self._text_parts.append(data)


def _normalize_result_url(href: str) -> str | None:
    href = unescape(href).strip()
    if not href:
        return None
    if href.startswith("//"):
        href = f"https:{href}"
    parsed = urlsplit(href)
    query = parse_qs(parsed.query)
    redirect = query.get("uddg")
    if redirect:
        href = unquote(redirect[0])
        parsed = urlsplit(href)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return href
    return None


def _url_with_query(endpoint: str, params: dict[str, str]) -> str:
    separator = "&" if "?" in endpoint else "?"
    return f"{endpoint}{separator}{urlencode(params, quote_via=quote_plus)}"


def _allowed_domains(allowed_domains: list[str]) -> tuple[str, ...]:
    return tuple(
        domain.strip().casefold().lstrip(".")
        for domain in allowed_domains
        if domain.strip()
    )


def _limit(value: Any) -> int:
    if value is None:
        return 10
    return max(1, min(int(value), 20))


def _timeout(value: Any) -> float:
    if value is None:
        return 10.0
    return max(0.1, min(float(value), 30.0))


def _collapse_text(value: str) -> str:
    return " ".join(unescape(value).split())
