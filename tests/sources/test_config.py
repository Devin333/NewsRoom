import json
from pathlib import Path

import pytest

from sources import SourceConfigError, load_source_definitions, load_source_registry


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
    assert openai.category == "official"
    assert openai.metadata["source_kind"] == "official_blog"


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
    assert registry.get("google-ai").source_type.value == "official_blog"
    assert registry.get("arxiv-ai").metadata["query"] == "cat:cs.AI"
    assert registry.get("arxiv-ai").metadata["config_section"] == "arxiv_categories"


def test_tracked_sources_config_uses_real_live_urls() -> None:
    registry = load_source_registry(Path("configs/sources.yaml"))
    sources = registry.list_sources(enabled_only=False)

    assert len(sources) >= 3
    assert all(not source.url.startswith("fixture://") for source in sources)
    assert {source.source_type.value for source in sources} >= {"rss", "official_blog", "arxiv"}
    assert registry.get("arxiv-cs-ai").metadata["query"] == "cat:cs.AI"
