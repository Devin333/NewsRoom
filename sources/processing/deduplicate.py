from __future__ import annotations

from domain.sources import NormalizedSourceItem


def deduplicate_items(items: list[NormalizedSourceItem]) -> list[NormalizedSourceItem]:
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    seen_content: set[str] = set()
    unique: list[NormalizedSourceItem] = []
    for item in items:
        if (
            item.canonical_url_hash in seen_urls
            or item.title_hash in seen_titles
            or item.content_hash in seen_content
        ):
            continue
        seen_urls.add(item.canonical_url_hash)
        seen_titles.add(item.title_hash)
        seen_content.add(item.content_hash)
        unique.append(item)
    return unique
