from __future__ import annotations

from typing import Any

from business.foundation import Signal


def source_reliability_source_payload(signal: Signal) -> dict[str, Any]:
    return {
        "name": signal.source.source_name,
        "url": signal.url or signal.source.source_url or "https://example.com",
        "publisher_type": publisher_type(signal.source.source_type.value),
        "known_reputation": str(signal.source.reliability.value),
    }


def source_reliability_content_payload(signal: Signal) -> dict[str, Any]:
    return {
        "title": signal.title,
        "url": signal.url or "",
        "published_at": signal.published_at.isoformat().replace("+00:00", "Z") if signal.published_at else "",
        "author": ", ".join(signal.authors),
        "raw_text": signal.content or signal.summary or signal.title,
    }


def signal_item_payload(signal: Signal) -> dict[str, Any]:
    return {
        "id": signal.signal_id,
        "item_id": signal.signal_id,
        "signal_id": signal.signal_id,
        "source_item_id": signal.source.external_id or signal.signal_id,
        "title": signal.title,
        "summary": signal.summary or "",
        "content": signal.content or "",
        "url": signal.url or "",
        "source_name": signal.source.source_name,
        "published_at": signal.published_at.isoformat().replace("+00:00", "Z") if signal.published_at else "",
        "entities": [],
    }


def card_report_item(card: Any) -> dict[str, Any]:
    payload = card.to_dict() if hasattr(card, "to_dict") else dict(card)
    evidence_refs = payload.get("evidence_refs") or []
    first_source = evidence_refs[0] if evidence_refs and isinstance(evidence_refs[0], dict) else {}
    return {
        "item_id": payload.get("card_id"),
        "title": payload.get("title"),
        "summary": payload.get("summary"),
        "url": first_source.get("url") or first_source.get("source_url") or "",
        "source_name": first_source.get("source_name") or "source",
        "evidence_status": "supported" if evidence_refs else "unclear",
        "trend_score": payload.get("score", {}).get("value", 0.5) if isinstance(payload.get("score"), dict) else 0.5,
        "why_it_matters": payload.get("ranking_reason") or payload.get("summary"),
    }


def summary_markdown(result: Any) -> str:
    title = f"{result.board_type.value} summary"
    lines = [f"# {title}", ""]
    for card in result.cards:
        lines.append(f"- {card.title}: {card.summary}")
    return "\n".join(lines) + "\n"


def publisher_type(source_type: str) -> str:
    if source_type in {"official_blog", "rss", "web_page", "html"}:
        return "official_blog" if source_type == "official_blog" else "news_media"
    if source_type in {"arxiv", "paper_index"}:
        return "research_platform"
    if source_type == "github":
        return "github"
    if source_type in {"hackernews", "reddit", "github_discussion", "lobsters", "stackoverflow", "devto"}:
        return "community"
    return "unknown"


__all__ = [
    "card_report_item",
    "publisher_type",
    "signal_item_payload",
    "source_reliability_content_payload",
    "source_reliability_source_payload",
    "summary_markdown",
]
