from business.foundation.models.source import SourceDefinition
from business.foundation.registry.source_registry import SourceRegistry


def test_source_registry_rejects_chinese_ai_media_category() -> None:
    registry = SourceRegistry(
        [
            SourceDefinition(
                source_id="paperweekly",
                name="PaperWeekly",
                source_type="rss",
                url="https://example.com/feed.xml",
                topics=["ai"],
                category="chinese_ai_media",
                language="zh",
                region="cn",
                metadata={"group": "chinese_ai_media", "priority": "p1", "signal_kind": "paper_digest"},
            )
        ]
    )

    result = registry.validate()

    assert result.is_valid is False
    assert any(
        issue.field == "category" and "chinese_ai_media" in issue.message
        for issue in result.errors
    )


def test_source_registry_validates_category_and_priority() -> None:
    registry = SourceRegistry(
        [
            SourceDefinition(
                source_id="bad",
                name="Bad",
                source_type="rss",
                url="https://example.com/feed.xml",
                topics=["ai"],
                category="community",
                metadata={"group": "developer_discussion", "priority": "p4", "signal_kind": "community_trend"},
            )
        ]
    )

    result = registry.validate()
    issues = {(issue.field, issue.severity) for issue in result.issues}

    assert result.is_valid is False
    assert ("category", "error") in issues
    assert ("metadata.priority", "error") in issues
    assert ("metadata.group", "warning") in issues


def test_source_registry_warns_for_missing_signal_kind_and_group_mismatch() -> None:
    registry = SourceRegistry(
        [
            SourceDefinition(
                source_id="openai-news",
                name="OpenAI News",
                source_type="rss",
                url="https://example.com/feed.xml",
                topics=["ai"],
                category="official_blog",
                metadata={"group": "research", "priority": "p0"},
            )
        ]
    )

    result = registry.validate()
    warnings = {(issue.field, issue.severity) for issue in result.warnings}

    assert result.is_valid is True
    assert ("metadata.group", "warning") in warnings
    assert ("metadata.signal_kind", "warning") in warnings


def test_source_registry_accepts_valid_ai_community_metadata() -> None:
    registry = SourceRegistry(
        [
            SourceDefinition(
                source_id="arxiv-cs-ai",
                name="arXiv cs.AI",
                source_type="arxiv",
                url="https://export.arxiv.org/api/query",
                topics=["ai", "papers"],
                category="research",
                metadata={"group": "research", "priority": "p0", "signal_kind": "paper"},
            )
        ]
    )

    assert registry.validate().is_valid is True
