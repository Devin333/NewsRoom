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


def test_source_registry_lists_sources_by_type() -> None:
    rss = SourceDefinition(
        source_id="rss",
        name="RSS",
        source_type="rss",
        url="https://example.com/rss.xml",
    )
    html = SourceDefinition(
        source_id="html",
        name="HTML",
        source_type="html",
        url="https://example.com/blog",
    )
    disabled_html = SourceDefinition(
        source_id="html-disabled",
        name="HTML Disabled",
        source_type="html",
        url="https://example.com/disabled",
        enabled=False,
    )

    registry = SourceRegistry([disabled_html, html, rss])

    assert registry.list_by_type("html") == [html]
    assert registry.list_by_type("html", enabled_only=False) == [html, disabled_html]


def test_source_registry_validates_html_backed_target_source_types() -> None:
    official_blog = SourceDefinition(
        source_id="official",
        name="Official Blog",
        source_type="official_blog",
        url="https://example.com/blog",
        topics=["ai"],
    )
    web_page = SourceDefinition(
        source_id="web-page",
        name="Web Page",
        source_type="web_page",
        url="ftp://example.com/page",
        topics=["ai"],
    )
    registry = SourceRegistry([official_blog, web_page])

    result = registry.validate()

    assert result.is_valid is False
    issues = {(issue.source_id, issue.field, issue.severity) for issue in result.issues}
    assert ("official", "url", "error") not in issues
    assert ("web-page", "url", "error") in issues


def test_source_registry_validates_social_fetchable_source_types() -> None:
    hackernews = SourceDefinition(
        source_id="hn",
        name="Hacker News",
        source_type="hackernews",
        url="https://hacker-news.firebaseio.com/v0",
        topics=["ai"],
    )
    reddit = SourceDefinition(
        source_id="reddit",
        name="Reddit",
        source_type="reddit",
        url="ftp://reddit.example/r/MachineLearning",
        topics=["ai"],
    )
    registry = SourceRegistry([hackernews, reddit])

    result = registry.validate()

    assert result.is_valid is False
    issues = {(issue.source_id, issue.field, issue.severity) for issue in result.issues}
    assert ("hn", "url", "error") not in issues
    assert ("reddit", "url", "error") in issues


def test_source_registry_lists_sources_by_reliability() -> None:
    high = SourceDefinition(
        source_id="high",
        name="High",
        source_type="rss",
        url="https://example.com/high.xml",
        reliability="high",
    )
    low = SourceDefinition(
        source_id="low",
        name="Low",
        source_type="rss",
        url="https://example.com/low.xml",
        reliability="low",
    )
    disabled_high = SourceDefinition(
        source_id="disabled-high",
        name="Disabled High",
        source_type="rss",
        url="https://example.com/disabled-high.xml",
        reliability="high",
        enabled=False,
    )

    registry = SourceRegistry([low, disabled_high, high])

    assert registry.list_by_reliability("high") == [high]
    assert registry.list_by_reliability("high", enabled_only=False) == [disabled_high, high]


def test_source_registry_lists_by_topic_with_language_and_region_filters() -> None:
    ai_us = SourceDefinition(
        source_id="ai-us",
        name="AI US",
        source_type="rss",
        url="https://example.com/ai-us.xml",
        topics=["ai", "policy"],
        language="en",
        region="us",
        reliability="high",
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
    assert registry.list_by_topic("AI policy", reliability="medium") == [ai_cn]


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


def test_source_registry_validate_reports_errors_and_warnings() -> None:
    invalid = SourceDefinition(
        source_id="invalid",
        name="Invalid",
        source_type="rss",
        url="ftp://example.com/feed.xml",
        authority_score=1.5,
    )
    valid_without_topics = SourceDefinition(
        source_id="valid",
        name="Valid",
        source_type="manual",
        url="manual://operator",
    )
    registry = SourceRegistry([valid_without_topics, invalid])

    result = registry.validate()
    payload = result.to_dict()

    assert result.is_valid is False
    assert payload["error_count"] == 2
    assert payload["warning_count"] == 2
    issues = {(issue.source_id, issue.field, issue.severity) for issue in result.issues}
    assert ("invalid", "authority_score", "error") in issues
    assert ("invalid", "url", "error") in issues
    assert ("valid", "topics", "warning") in issues


def test_source_registry_validate_reports_governance_errors() -> None:
    fixture = SourceDefinition(
        source_id="fixture-source",
        name="Fixture Source",
        source_type="rss",
        url="fixture://feed",
        topics=["ai"],
        metadata={"headers": {"api_key": "hidden"}},
    )
    unsafe_id = SourceDefinition(
        source_id="feed/source",
        name="Unsafe ID",
        source_type="manual",
        url="manual://operator",
        topics=["ai"],
        metadata={"nested": [{"refresh_token": "hidden"}]},
    )
    registry = SourceRegistry([fixture, unsafe_id])

    result = registry.validate()

    assert result.is_valid is False
    issues = {(issue.source_id, issue.field, issue.severity) for issue in result.issues}
    assert ("fixture-source", "url", "error") in issues
    assert ("fixture-source", "metadata.headers.api_key", "error") in issues
    assert ("feed/source", "source_id", "error") in issues
    assert ("feed/source", "metadata.nested[0].refresh_token", "error") in issues
