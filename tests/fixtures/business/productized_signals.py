from __future__ import annotations

from typing import Any


def sample_ai_news_productized_signals() -> list[dict[str, Any]]:
    return [
        _signal("ai_news", 1, title="OpenAI Agent Memory product update", source_type="official_blog", reliability="high", tags=["ai_news", "product_update"]),
        _signal("ai_news", 2, title="OpenAI Agent Memory product update", source_type="rss", reliability="high", tags=["ai_news", "industry"]),
        _signal("ai_news", 3, title="Sparse Agent Memory launch note", source_type="web_page", reliability="medium", sparse=True, tags=["ai_news"]),
        _signal("ai_news", 4, title="Low confidence AI market rumor", source_type="web_page", reliability="low", tags=["industry"]),
        _signal("ai_news", 5, title="Microsoft and OpenAI expand Agent Memory workflows", source_type="rss", reliability="high", tags=["ai_news", "subscription"]),
    ]


def sample_project_radar_productized_signals() -> list[dict[str, Any]]:
    return [
        _signal("github_project", 1, title="LangChain releases Agent Memory framework", source_type="github", reliability="high", tags=["github", "release"]),
        _signal("github_project", 2, title="LangChain releases Agent Memory framework", source_type="github", reliability="high", tags=["github", "duplicate"]),
        _signal("github_project", 3, title="Sparse MCP project note", source_type="github", reliability="medium", sparse=True, tags=["project"]),
        _signal("github_project", 4, title="Low quality framework mirror", source_type="devto", reliability="low", tags=["framework"]),
        _signal("github_project", 5, title="LlamaIndex adds MCP integration", source_type="hackernews", reliability="high", tags=["github", "framework", "subscription"]),
    ]


def sample_paper_radar_productized_signals() -> list[dict[str, Any]]:
    return [
        _signal("paper", 1, title="Agent Memory benchmark on RAG workflows", source_type="arxiv", reliability="high", tags=["paper", "benchmark"]),
        _signal("paper", 2, title="Agent Memory benchmark on RAG workflows", source_type="arxiv", reliability="high", tags=["paper", "duplicate"]),
        _signal("paper", 3, title="Sparse MCP benchmark abstract", source_type="paper_index", reliability="medium", sparse=True, tags=["research"]),
        _signal("paper", 4, title="Low confidence paper summary", source_type="paper_index", reliability="low", tags=["paper"]),
        _signal("paper", 5, title="OpenAI workflow evaluation paper", source_type="arxiv", reliability="high", tags=["arxiv", "research", "subscription"]),
    ]


def sample_community_pulse_productized_signals() -> list[dict[str, Any]]:
    return [
        _signal("community_discussion", 1, title="Developers discuss OpenAI Agent Memory", source_type="hackernews", reliability="high", tags=["community", "discussion"]),
        _signal("community_discussion", 2, title="Developers discuss OpenAI Agent Memory", source_type="reddit", reliability="medium", tags=["community", "duplicate"]),
        _signal("community_discussion", 3, title="Sparse MCP thread", source_type="lobsters", reliability="medium", sparse=True, tags=["developer"]),
        _signal("community_discussion", 4, title="Low quality sentiment post", source_type="devto", reliability="low", tags=["sentiment"]),
        _signal("community_discussion", 5, title="StackOverflow asks about LangChain Agent Memory", source_type="stackoverflow", reliability="high", tags=["community", "developer", "subscription"]),
    ]


def sample_mixed_productized_signals() -> list[dict[str, Any]]:
    return [
        *sample_ai_news_productized_signals(),
        *sample_project_radar_productized_signals(),
        *sample_paper_radar_productized_signals(),
        *sample_community_pulse_productized_signals(),
        _signal("ai_news", 99, title="Irrelevant mixed logistics update", source_type="manual", reliability="low", tags=["irrelevant"]),
    ]


def _signal(
    signal_type: str,
    index: int,
    *,
    title: str,
    source_type: str,
    reliability: str,
    tags: list[str],
    sparse: bool = False,
) -> dict[str, Any]:
    summary = (
        "OpenAI, Microsoft, LangChain, LlamaIndex, RAG, MCP, and Agent Memory appear in this productized fixture signal."
        if not sparse
        else "Agent Memory short note."
    )
    authority = {"high": 0.92, "medium": 0.65, "low": 0.25}.get(reliability, 0.5)
    return {
        "source_item_id": f"{signal_type}-{index}",
        "source_id": f"{source_type}-source-{index}",
        "source_name": f"{source_type.title()} Source",
        "source_type": source_type,
        "signal_type": signal_type,
        "title": title,
        "summary": summary,
        "content": summary,
        "url": f"https://example.com/{signal_type}/{index}",
        "language": "en",
        "authors": ["Fixture Author"],
        "tags": tags,
        "fetched_at": "2026-05-19T01:00:00Z",
        "published_at": "2026-05-19T00:00:00Z",
        "metadata": {
            "source_reliability": reliability,
            "source_authority_score": authority,
            "fixture_kind": "productized_acceptance",
        },
    }


__all__ = [
    "sample_ai_news_productized_signals",
    "sample_project_radar_productized_signals",
    "sample_paper_radar_productized_signals",
    "sample_community_pulse_productized_signals",
    "sample_mixed_productized_signals",
]
