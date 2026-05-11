from domain.sources import SourceDefinition
from sources import SourceRegistry


def test_source_registry_lists_enabled_sources_only_by_default() -> None:
    enabled = SourceDefinition(
        source_id="enabled",
        name="Enabled",
        source_type="rss",
        url="https://example.com/enabled.xml",
    )
    disabled = SourceDefinition(
        source_id="disabled",
        name="Disabled",
        source_type="rss",
        url="https://example.com/disabled.xml",
        enabled=False,
    )

    registry = SourceRegistry([disabled, enabled])

    assert registry.list_sources() == [enabled]
    assert registry.list_sources(enabled_only=False) == [disabled, enabled]


def test_source_registry_lists_by_topic_with_language_and_region_filters() -> None:
    ai_us = SourceDefinition(
        source_id="ai-us",
        name="AI US",
        source_type="rss",
        url="https://example.com/ai-us.xml",
        topics=["ai", "policy"],
        language="en",
        region="us",
    )
    ai_cn = SourceDefinition(
        source_id="ai-cn",
        name="AI CN",
        source_type="rss",
        url="https://example.com/ai-cn.xml",
        topics=["ai"],
        language="zh",
        region="cn",
    )
    chips = SourceDefinition(
        source_id="chips",
        name="Chips",
        source_type="rss",
        url="https://example.com/chips.xml",
        topics=["semiconductors"],
        language="en",
        region="us",
    )

    registry = SourceRegistry([chips, ai_cn, ai_us])

    assert registry.list_by_topic("AI policy", language="en", region="us") == [ai_us]


def test_source_registry_select_sources_orders_by_match_reliability_authority() -> None:
    low_quality = SourceDefinition(
        source_id="b-low",
        name="Low",
        source_type="rss",
        url="https://example.com/low.xml",
        topics=["ai"],
        reliability="low",
        authority_score=1.0,
    )
    high_quality = SourceDefinition(
        source_id="a-high",
        name="High",
        source_type="rss",
        url="https://example.com/high.xml",
        topics=["ai", "policy"],
        reliability="high",
        authority_score=0.3,
    )
    medium_quality = SourceDefinition(
        source_id="c-medium",
        name="Medium",
        source_type="rss",
        url="https://example.com/medium.xml",
        topics=["ai"],
        reliability="medium",
        authority_score=0.8,
    )

    registry = SourceRegistry([low_quality, medium_quality, high_quality])

    assert registry.select_sources(topic="AI policy") == [high_quality, medium_quality, low_quality]


def test_source_registry_select_sources_falls_back_to_enabled_sources() -> None:
    enabled = SourceDefinition(
        source_id="enabled",
        name="Enabled",
        source_type="rss",
        url="https://example.com/enabled.xml",
        topics=["ai"],
        authority_score=0.2,
    )
    better = SourceDefinition(
        source_id="better",
        name="Better",
        source_type="rss",
        url="https://example.com/better.xml",
        topics=["policy"],
        reliability="high",
        authority_score=0.9,
    )
    disabled = SourceDefinition(
        source_id="disabled",
        name="Disabled",
        source_type="rss",
        url="https://example.com/disabled.xml",
        topics=["sports"],
        enabled=False,
        authority_score=1.0,
    )

    registry = SourceRegistry([disabled, enabled, better])

    assert registry.select_sources(topic="weather") == [better, enabled]
    assert registry.select_sources(topic="weather", fallback_to_enabled=False) == []
