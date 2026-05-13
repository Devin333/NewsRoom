import json
from pathlib import Path

import pytest

from sources import (
    SourceConfigError,
    load_source_definitions,
    load_source_fetch_policy,
    load_source_registry,
)


def test_load_source_registry_reads_json_sources_payload(tmp_path) -> None:
    config_path = tmp_path / "sources.json"
    config_path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "source_id": "openai",
                        "name": "OpenAI News",
                        "source_type": "rss",
                        "url": "https://openai.com/news/rss.xml",
                        "reliability": "high",
                        "authority_score": 0.9,
                        "fetch_interval_seconds": 1800,
                        "user_agent": "NewsRoomTest/1.0",
                        "topics": ["ai", "models"],
                        "category": "official",
                        "language": "en",
                        "metadata": {"source_kind": "official_blog"},
                    },
                    {
                        "source_id": "hn",
                        "name": "Hacker News",
                        "source_type": "hackernews",
                        "url": "https://hacker-news.firebaseio.com/v0",
                        "topics": ["technology"],
                        "metadata": {"story_list": "topstories"},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    registry = load_source_registry(config_path)

    assert [source.source_id for source in registry.list_sources()] == ["hn", "openai"]
    openai = registry.get("openai")
    assert openai.reliability.value == "high"
    assert openai.authority_score == 0.9
    assert openai.fetch_interval_seconds == 1800
    assert openai.user_agent == "NewsRoomTest/1.0"
    assert openai.category == "official"
    assert openai.metadata["source_kind"] == "official_blog"


def test_load_source_fetch_policy_reads_top_level_fetch_config(tmp_path) -> None:
    config_path = tmp_path / "sources.json"
    config_path.write_text(
        json.dumps(
            {
                "fetch": {
                    "timeout_seconds": 9.5,
                    "max_bytes": 2048,
                    "max_redirects": 4,
                    "user_agent": "NewsRoomFetchTest/1.0",
                    "respect_robots": False,
                    "rate_limit_per_domain_per_minute": 12,
                    "retry_times": 3,
                    "retry_on_status_codes": [429, 503],
                },
                "sources": [
                    {
                        "source_id": "openai",
                        "name": "OpenAI News",
                        "source_type": "rss",
                        "url": "https://openai.com/news/rss.xml",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    policy = load_source_fetch_policy(config_path)

    assert policy.timeout_seconds == 9.5
    assert policy.max_bytes == 2048
    assert policy.max_redirects == 4
    assert policy.user_agent == "NewsRoomFetchTest/1.0"
    assert policy.respect_robots is False
    assert policy.rate_limit_per_domain_per_minute == 12
    assert policy.retry_times == 3
    assert policy.retry_on_status_codes == (429, 503)


def test_load_source_fetch_policy_rejects_invalid_fetch_config(tmp_path) -> None:
    config_path = tmp_path / "sources.json"
    config_path.write_text(
        json.dumps(
            {
                "fetch": "fast",
                "sources": [
                    {
                        "source_id": "openai",
                        "name": "OpenAI News",
                        "source_type": "rss",
                        "url": "https://openai.com/news/rss.xml",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SourceConfigError, match="source fetch config"):
        load_source_fetch_policy(config_path)


def test_load_source_definitions_reads_top_level_toml_sources(tmp_path) -> None:
    config_path = tmp_path / "sources.toml"
    config_path.write_text(
        """
[[sources]]
source_id = "reddit"
name = "Reddit MachineLearning"
source_type = "reddit"
url = "https://www.reddit.com"
topics = ["ai", "machine learning"]
language = "en"

[sources.metadata]
subreddit = "MachineLearning"
listing = "new"
""".strip(),
        encoding="utf-8",
    )

    definitions = load_source_definitions(config_path)

    assert len(definitions) == 1
    assert definitions[0].source_type.value == "reddit"
    assert definitions[0].metadata["subreddit"] == "MachineLearning"


def test_load_source_registry_rejects_invalid_validated_config(tmp_path) -> None:
    config_path = tmp_path / "sources.json"
    config_path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "source_id": "bad",
                        "name": "Bad",
                        "source_type": "rss",
                        "url": "fixture://bad",
                        "topics": ["ai"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SourceConfigError, match="bad.url"):
        load_source_registry(config_path)


def test_load_source_registry_rejects_invalid_fetch_interval(tmp_path) -> None:
    config_path = tmp_path / "sources.json"
    config_path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "source_id": "bad",
                        "name": "Bad",
                        "source_type": "rss",
                        "url": "https://example.com/rss.xml",
                        "topics": ["ai"],
                        "fetch_interval_seconds": 0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SourceConfigError, match="fetch_interval_seconds"):
        load_source_registry(config_path)


def test_load_source_registry_rejects_source_url_credentials(tmp_path) -> None:
    config_path = tmp_path / "sources.json"
    config_path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "source_id": "bad",
                        "name": "Bad",
                        "source_type": "rss",
                        "url": "https://example.com/rss.xml?api_key=hidden",
                        "topics": ["ai"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SourceConfigError, match=r"url\.query\.api_key"):
        load_source_registry(config_path)


def test_load_source_registry_requires_supported_file_type(tmp_path) -> None:
    config_path = tmp_path / "sources.txt"
    config_path.write_text("sources = []", encoding="utf-8")

    with pytest.raises(SourceConfigError, match="unsupported"):
        load_source_registry(config_path)


def test_load_source_registry_reads_prd_section_config(tmp_path) -> None:
    config_path = tmp_path / "sources.yaml"
    config_path.write_text(
        """
fetch:
  timeout_seconds: 15
rss_feeds:
  - source_id: openai
    name: OpenAI News
    url: https://openai.com/news/rss.xml
    reliability: high
    fetch_interval_seconds: 1200
    user_agent: NewsRoomSource/1.0
    topics: [ai]
official_blogs:
  - source_id: google-ai
    name: Google AI Blog
    url: https://blog.google/technology/ai/rss/
    topics: [ai, research]
arxiv_categories:
  - source_id: arxiv-ai
    name: arXiv AI
    url: https://export.arxiv.org/api/query
    topics: [ai, papers]
    query: cat:cs.AI
github_lists: []
""".strip(),
        encoding="utf-8",
    )

    registry = load_source_registry(config_path)

    assert [source.source_id for source in registry.list_sources()] == [
        "arxiv-ai",
        "google-ai",
        "openai",
    ]
    assert registry.get("openai").source_type.value == "rss"
    assert registry.get("openai").fetch_interval_seconds == 1200
    assert registry.get("openai").user_agent == "NewsRoomSource/1.0"
    assert registry.get("google-ai").source_type.value == "official_blog"
    assert registry.get("arxiv-ai").metadata["query"] == "cat:cs.AI"
    assert registry.get("arxiv-ai").metadata["config_section"] == "arxiv_categories"


def test_load_source_registry_reads_target_source_sections(tmp_path) -> None:
    config_path = tmp_path / "sources.yaml"
    config_path.write_text(
        """
web_pages:
  - source_id: model-card
    name: Model Card
    url: https://example.com/model-card
    topics: [ai]
manual_sources:
  - source_id: operator-list
    name: Operator List
    url: manual://operator
    topics: [ai]
    records:
      - title: Manual item
        url: https://example.com/manual
hackernews_sources:
  - source_id: hn-top
    name: HN Top
    url: https://hacker-news.firebaseio.com/v0
    topics: [technology]
    story_list: topstories
reddit_sources:
  - source_id: reddit-ml
    name: Reddit ML
    url: https://www.reddit.com
    topics: [ai]
    subreddit: MachineLearning
lobsters_sources:
  - source_id: lobsters-ai
    name: Lobsters AI
    url: https://lobste.rs
    topics: [ai]
    tag: ai
stackoverflow_tags:
  - source_id: stackoverflow-ai
    name: Stack Overflow AI
    url: https://api.stackexchange.com/2.3
    topics: [ai]
    tag: artificial-intelligence
devto_tags:
  - source_id: devto-ai
    name: dev.to AI
    url: https://dev.to/api
    topics: [ai]
    tag: ai
medium_feeds:
  - source_id: medium-ai
    name: Medium AI
    url: https://medium.com/feed/tag/artificial-intelligence
    topics: [ai]
""".strip(),
        encoding="utf-8",
    )

    registry = load_source_registry(config_path)

    assert registry.get("model-card").source_type.value == "web_page"
    assert registry.get("operator-list").source_type.value == "manual"
    assert registry.get("operator-list").metadata["records"][0]["title"] == "Manual item"
    assert registry.get("hn-top").source_type.value == "hackernews"
    assert registry.get("hn-top").metadata["story_list"] == "topstories"
    assert registry.get("reddit-ml").source_type.value == "reddit"
    assert registry.get("reddit-ml").metadata["subreddit"] == "MachineLearning"
    assert registry.get("lobsters-ai").source_type.value == "lobsters"
    assert registry.get("lobsters-ai").metadata["tag"] == "ai"
    assert registry.get("stackoverflow-ai").source_type.value == "stackoverflow"
    assert registry.get("stackoverflow-ai").metadata["tag"] == "artificial-intelligence"
    assert registry.get("devto-ai").source_type.value == "devto"
    assert registry.get("devto-ai").metadata["tag"] == "ai"
    assert registry.get("medium-ai").source_type.value == "medium"
    assert registry.get("medium-ai").metadata["config_section"] == "medium_feeds"


def test_tracked_sources_config_uses_real_live_urls() -> None:
    registry = load_source_registry(Path("configs/sources.yaml"))
    sources = registry.list_sources(enabled_only=False)

    assert len(sources) >= 3
    assert all(not source.url.startswith("fixture://") for source in sources)
    assert {source.source_type.value for source in sources} >= {"rss", "official_blog", "arxiv"}
    assert registry.get("arxiv-cs-ai").metadata["query"] == "cat:cs.AI"
