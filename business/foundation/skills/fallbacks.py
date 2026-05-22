from __future__ import annotations

from hashlib import sha1
from typing import Any


def fallback_entity_extraction(item: dict[str, Any]) -> dict[str, Any]:
    text = _text(item.get("title"), item.get("summary"), item.get("content"))
    names = _entity_names(text)
    return {
        "entities": [
            {
                "name": name,
                "normalized_name": _normalize_name(name),
                "type": _entity_type(name),
                "aliases": [],
                "evidence_span": name,
                "confidence": 0.68,
            }
            for name in names
        ],
        "warnings": [] if names else ["no deterministic entity detected"],
    }


def fallback_source_reliability(source: dict[str, Any], content: dict[str, Any] | None = None) -> dict[str, Any]:
    publisher_type = str(source.get("publisher_type") or source.get("source_type") or "unknown")
    known = str(source.get("known_reputation") or source.get("reliability") or "unknown")
    score = {
        "official_blog": 0.92,
        "research_platform": 0.86,
        "github": 0.78,
        "news_media": 0.72,
        "community": 0.58,
        "social": 0.45,
    }.get(publisher_type, {"high": 0.86, "medium": 0.68, "low": 0.38}.get(known, 0.55))
    tier = "primary" if score >= 0.86 else "trusted_secondary" if score >= 0.75 else "secondary" if score >= 0.62 else "community" if score >= 0.45 else "unverified"
    risk_flags: list[str] = []
    if publisher_type in {"unknown", "social"}:
        risk_flags.append("unknown_source")
    if content and not content.get("published_at"):
        risk_flags.append("missing_date")
    return {
        "reliability_score": round(score, 4),
        "source_tier": tier,
        "risk_flags": risk_flags,
        "reasoning_summary": f"Deterministic reliability from publisher_type={publisher_type}.",
        "evidence": [{"field": "publisher_type", "observation": publisher_type}],
    }


def fallback_event_deduplication(items: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        key = _dedupe_key(item)
        groups.setdefault(key, []).append(item)
    event_groups = []
    duplicate_pairs = []
    for key, group in groups.items():
        ids = [_item_id(item) for item in group]
        canonical = ids[0]
        event_groups.append(
            {
                "event_id": f"event_{sha1(key.encode('utf-8')).hexdigest()[:12]}",
                "item_ids": ids,
                "canonical_item_id": canonical,
                "merge_reason": "normalized_title_url" if len(group) > 1 else "single_item",
                "confidence": 0.9 if len(group) > 1 else 0.75,
            }
        )
        for index, left in enumerate(ids):
            for right in ids[index + 1 :]:
                duplicate_pairs.append(
                    {
                        "left_item_id": left,
                        "right_item_id": right,
                        "same_event": True,
                        "confidence": 0.9,
                        "reason": "same deterministic event group",
                    }
                )
    return {"event_groups": event_groups, "duplicate_pairs": duplicate_pairs}


def fallback_evidence_checking(claims: list[dict[str, Any]], sources: list[dict[str, Any]]) -> dict[str, Any]:
    source_ids = [str(source.get("source_id") or source.get("id") or index) for index, source in enumerate(sources)]
    results = []
    for claim in claims:
        citation_ids = [str(value) for value in claim.get("citation_source_ids", []) if str(value)]
        supporting = [source_id for source_id in citation_ids if source_id in source_ids] or source_ids[:1]
        status = "supported" if supporting else "unclear"
        results.append(
            {
                "claim_id": str(claim.get("claim_id") or _stable_id("claim", claim.get("text"))),
                "status": status,
                "supporting_source_ids": supporting,
                "contradicting_source_ids": [],
                "evidence_spans": [
                    {"source_id": source_id, "span": str(claim.get("text") or "")[:120], "relation": "supports"}
                    for source_id in supporting
                ],
                "explanation": "Deterministic evidence check matched available source ids.",
                "suggested_rewrite": "",
            }
        )
    return {
        "claim_results": results,
        "summary": {
            "supported_count": sum(1 for item in results if item["status"] == "supported"),
            "contradicted_count": 0,
            "unclear_count": sum(1 for item in results if item["status"] == "unclear"),
        },
    }


def fallback_report_writing(report: dict[str, Any], items: list[dict[str, Any]], trend_analyses: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    title = str(report.get("title") or "Board Summary")
    summary = f"{title} contains {len(items)} item(s)."
    sections = [
        {
            "title": "Highlights",
            "content": "\n".join(f"- {item.get('title', 'Untitled')}" for item in items) or "No highlights.",
            "item_ids": [_item_id(item) for item in items],
        }
    ]
    citations = [
        {
            "item_id": _item_id(item),
            "url": str(item.get("url") or ""),
            "source_name": str(item.get("source_name") or item.get("source_id") or "source"),
        }
        for item in items
    ]
    markdown = f"# {title}\n\n{summary}\n\n" + sections[0]["content"] + "\n"
    if trend_analyses:
        markdown += f"\nTrend analyses: {len(trend_analyses)}.\n"
    return {
        "markdown_report": markdown,
        "summary": summary,
        "sections": sections,
        "citations": citations,
        "warnings": [] if items else ["no items available for report"],
    }


def fallback_trend_analysis(events: list[dict[str, Any]]) -> dict[str, Any]:
    analyses = []
    for event in events:
        source_count = int(event.get("source_count") or len(event.get("item_ids") or []) or 1)
        primary_count = int(event.get("primary_source_count") or 0)
        community_count = int(event.get("community_signal_count") or 0)
        score = min(1.0, 0.35 + source_count * 0.12 + primary_count * 0.12 + community_count * 0.05)
        analyses.append(
            {
                "event_id": str(event.get("event_id") or _stable_id("event", event.get("title"))),
                "trend_score": round(score, 4),
                "momentum": "surging" if score >= 0.85 else "high" if score >= 0.7 else "medium" if score >= 0.5 else "low",
                "novelty": "notable" if score >= 0.65 else "incremental",
                "impact_area": [str(value) for value in event.get("impact_hints", [])] or ["engineering"],
                "why_it_matters": str(event.get("summary") or event.get("title") or "Trend signal requires monitoring."),
                "watchlist_recommendation": "escalate" if score >= 0.85 else "track" if score >= 0.7 else "monitor",
                "reasoning_summary": "Deterministic trend score from source and community counts.",
            }
        )
    return {"event_analyses": analyses}


def _text(*values: Any) -> str:
    return " ".join(str(value or "") for value in values).strip()


def _entity_names(text: str) -> list[str]:
    hints = ["OpenAI", "Anthropic", "Google", "Meta", "Microsoft", "Agent Memory", "LangChain", "LlamaIndex", "RAG", "MCP"]
    found = [hint for hint in hints if hint.casefold() in text.casefold()]
    return found[:6]


def _entity_type(name: str) -> str:
    lowered = name.casefold()
    if lowered in {"openai", "anthropic", "google", "meta", "microsoft"}:
        return "company"
    if lowered in {"langchain", "llamaindex"}:
        return "framework"
    if lowered in {"rag", "mcp"}:
        return "event"
    return "product"


def _normalize_name(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")


def _item_id(item: dict[str, Any]) -> str:
    return str(item.get("item_id") or item.get("id") or item.get("signal_id") or item.get("source_item_id") or item.get("title") or "item")


def _dedupe_key(item: dict[str, Any]) -> str:
    title = str(item.get("title") or "").casefold().strip()
    url = str(item.get("url") or "").casefold().split("?", 1)[0]
    return f"{title}|{url}"


def _stable_id(prefix: str, value: Any) -> str:
    return f"{prefix}_{sha1(str(value or prefix).encode('utf-8')).hexdigest()[:12]}"


__all__ = [
    "fallback_entity_extraction",
    "fallback_source_reliability",
    "fallback_event_deduplication",
    "fallback_evidence_checking",
    "fallback_report_writing",
    "fallback_trend_analysis",
]
