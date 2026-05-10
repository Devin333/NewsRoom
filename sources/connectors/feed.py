from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from hashlib import sha256
from typing import Callable
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from domain.sources import RawSourceItem, SourceDefinition, SourceError, SourceType


FetchText = Callable[[str], str]


class FeedConnector:
    def __init__(self, fetch_text: FetchText | None = None) -> None:
        self._fetch_text = fetch_text or self._default_fetch_text

    def fetch(self, source: SourceDefinition, *, limit: int | None = None) -> tuple[list[RawSourceItem], list[SourceError]]:
        try:
            xml_text = self._fetch_text(source.url)
            return self.parse(source, xml_text, limit=limit), []
        except Exception as exc:
            return [], [
                SourceError(
                    source_id=source.source_id,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    url=source.url,
                )
            ]

    def parse(self, source: SourceDefinition, xml_text: str, *, limit: int | None = None) -> list[RawSourceItem]:
        root = ElementTree.fromstring(xml_text)
        fetched_at = datetime.now(UTC)
        if _local_name(root.tag) == "rss":
            items = self._parse_rss(source, root, fetched_at)
        elif _local_name(root.tag) == "feed":
            items = self._parse_atom(source, root, fetched_at)
        else:
            raise ValueError(f"unsupported feed root: {_local_name(root.tag)}")
        return items[:limit] if limit else items

    def _parse_rss(
        self,
        source: SourceDefinition,
        root: ElementTree.Element,
        fetched_at: datetime,
    ) -> list[RawSourceItem]:
        channel = root.find("channel")
        if channel is None:
            raise ValueError("rss feed missing channel")
        raw_items = []
        for item in channel.findall("item"):
            title = _text(item, "title")
            url = _text(item, "link")
            if not title or not url:
                continue
            raw_items.append(
                _raw_item(
                    source=source,
                    title=title,
                    url=url,
                    fetched_at=fetched_at,
                    published_at=_parse_datetime(_text(item, "pubDate")),
                    summary=_text(item, "description"),
                    raw_content=ElementTree.tostring(item, encoding="unicode"),
                )
            )
        return raw_items

    def _parse_atom(
        self,
        source: SourceDefinition,
        root: ElementTree.Element,
        fetched_at: datetime,
    ) -> list[RawSourceItem]:
        raw_items = []
        for entry in _children(root, "entry"):
            title = _child_text(entry, "title")
            url = _atom_link(entry)
            if not title or not url:
                continue
            raw_items.append(
                _raw_item(
                    source=source,
                    title=title,
                    url=url,
                    fetched_at=fetched_at,
                    published_at=_parse_datetime(
                        _child_text(entry, "published") or _child_text(entry, "updated")
                    ),
                    summary=_child_text(entry, "summary") or _child_text(entry, "content"),
                    raw_content=ElementTree.tostring(entry, encoding="unicode"),
                )
            )
        return raw_items

    def _default_fetch_text(self, url: str) -> str:
        request = Request(url, headers={"User-Agent": "NewsRoom/0.1"})
        with urlopen(request, timeout=15) as response:
            return response.read(1_000_000).decode("utf-8", errors="replace")


def _raw_item(
    *,
    source: SourceDefinition,
    title: str,
    url: str,
    fetched_at: datetime,
    published_at: datetime | None,
    summary: str | None,
    raw_content: str,
) -> RawSourceItem:
    item_hash = sha256(f"{source.source_id}|{url}".encode("utf-8")).hexdigest()
    return RawSourceItem(
        source_item_id=f"raw_{item_hash[:16]}",
        source_id=source.source_id,
        source_name=source.name,
        source_type=source.source_type,
        title=title.strip(),
        url=url.strip(),
        fetched_at=fetched_at,
        published_at=published_at,
        summary=summary.strip() if summary else None,
        raw_content=raw_content,
        language=source.language,
        metadata={"source_reliability": source.reliability.value},
    )


def _text(parent: ElementTree.Element, tag: str) -> str | None:
    child = parent.find(tag)
    return child.text.strip() if child is not None and child.text else None


def _children(parent: ElementTree.Element, local_name: str) -> list[ElementTree.Element]:
    return [child for child in list(parent) if _local_name(child.tag) == local_name]


def _child_text(parent: ElementTree.Element, local_name: str) -> str | None:
    for child in _children(parent, local_name):
        return child.text.strip() if child.text else None
    return None


def _atom_link(entry: ElementTree.Element) -> str | None:
    for child in _children(entry, "link"):
        href = child.attrib.get("href")
        if href and child.attrib.get("rel", "alternate") == "alternate":
            return href.strip()
    return None


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except (TypeError, ValueError):
        pass
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except ValueError:
        return None
