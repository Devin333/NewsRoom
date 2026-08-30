from backend.foundation.models.source import SourceDefinition
from backend.foundation.registry.source_registry import SourceRegistry


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


def test_source_registry_registers_and_finds_connector_by_source_type() -> None:
    connector = object()
    registry = SourceRegistry(connectors={"rss": connector})

    assert registry.get_connector("rss") is connector

    html_connector = object()
    registry.register_connector("html", html_connector)

    assert registry.get_connector("html") is html_connector


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


def test_source_registry_validates_developer_community_source_types() -> None:
    registry = SourceRegistry(
        [
            SourceDefinition(
                source_id="lobsters",
                name="Lobsters",
                source_type="lobsters",
                url="https://lobste.rs",
                topics=["ai"],
            ),
            SourceDefinition(
                source_id="stackoverflow",
                name="Stack Overflow",
                source_type="stackoverflow",
                url="https://api.stackexchange.com/2.3",
                topics=["ai"],
            ),
            SourceDefinition(
                source_id="devto",
                name="dev.to",
                source_type="devto",
                url="https://dev.to/api",
                topics=["ai"],
            ),
            SourceDefinition(
                source_id="medium",
                name="Medium",
                source_type="medium",
                url="ftp://medium.example/feed",
                topics=["ai"],
            ),
        ]
    )

    result = registry.validate()

    issues = {(issue.source_id, issue.field, issue.severity) for issue in result.issues}
    assert ("lobsters", "url", "error") not in issues
    assert ("stackoverflow", "url", "error") not in issues
    assert ("devto", "url", "error") not in issues
    assert ("medium", "url", "error") in issues


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


def test_source_registry_lists_and_filters_by_category() -> None:
    official = SourceDefinition(
        source_id="official",
        name="Official",
        source_type="rss",
        url="https://example.com/official.xml",
        topics=["ai"],
        category="official",
    )
    community = SourceDefinition(
        source_id="community",
        name="Community",
        source_type="rss",
        url="https://example.com/community.xml",
        topics=["ai"],
        category="community",
        reliability="low",
    )
    registry = SourceRegistry([community, official])

    assert registry.list_by_category("official") == [official]
    assert registry.select_sources(topic="AI", category="community") == [community]


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

    selected, report = registry.select_sources_with_report(topic="weather")

    assert selected == [better, enabled]
    assert report.topic == "weather"
    assert report.matched_source_count == 0
    assert report.selected_source_count == 2
    assert report.fallback_used is True
    assert report.fallback_reason == "no_topic_match"
    assert report.selected_source_ids == ["better", "enabled"]
    assert report.filters["fallback_to_enabled"] is True


def test_source_registry_selection_report_records_topic_matches() -> None:
    official = SourceDefinition(
        source_id="official",
        name="Official",
        source_type="rss",
        url="https://example.com/official.xml",
        topics=["ai", "policy"],
        language="en",
        reliability="high",
        authority_score=0.9,
        fetch_interval_seconds=900,
        user_agent="NewsRoomSource/1.0",
    )
    unrelated = SourceDefinition(
        source_id="unrelated",
        name="Unrelated",
        source_type="rss",
        url="https://example.com/unrelated.xml",
        topics=["sports"],
        language="en",
    )
    registry = SourceRegistry([unrelated, official])

    selected, report = registry.select_sources_with_report(topic="AI policy", language="en")
    payload = report.to_dict()

    assert selected == [official]
    assert report.fallback_used is False
    assert payload["matched_source_count"] == 1
    assert payload["selected_source_ids"] == ["official"]
    assert payload["selected_sources"][0]["source_type"] == "rss"
    assert payload["selected_sources"][0]["reliability"] == "high"
    assert payload["selected_sources"][0]["fetch_interval_seconds"] == 900
    assert payload["selected_sources"][0]["respect_robots"] is True
    assert payload["selected_sources"][0]["user_agent"] == "NewsRoomSource/1.0"
    assert payload["filters"] == {
        "enabled_only": True,
        "language": "en",
        "fallback_to_enabled": True,
    }


def test_source_definition_validates_fetch_policy_fields() -> None:
    try:
        SourceDefinition(
            source_id="bad-interval",
            name="Bad Interval",
            source_type="rss",
            url="https://example.com/rss.xml",
            fetch_interval_seconds=0,
        )
    except ValueError as exc:
        assert "fetch_interval_seconds" in str(exc)
    else:
        raise AssertionError("expected fetch_interval_seconds validation failure")

    try:
        SourceDefinition(
            source_id="bad-user-agent",
            name="Bad User Agent",
            source_type="rss",
            url="https://example.com/rss.xml",
            user_agent=" ",
        )
    except ValueError as exc:
        assert "user_agent" in str(exc)
    else:
        raise AssertionError("expected user_agent validation failure")


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
    assert payload["warning_count"] >= 2
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


def test_source_registry_validate_rejects_url_embedded_credentials() -> None:
    source = SourceDefinition(
        source_id="credential-url",
        name="Credential URL",
        source_type="rss",
        url=(
            "https://user:hidden-password@example.com/feed.xml"
            "?access_token=hidden-token&X-Amz-Signature=hidden-signature"
        ),
        topics=["ai"],
    )
    registry = SourceRegistry([source])

    result = registry.validate()

    assert result.is_valid is False
    issues = {(issue.source_id, issue.field, issue.severity) for issue in result.issues}
    assert ("credential-url", "url.userinfo", "error") in issues
    assert ("credential-url", "url.query.access_token", "error") in issues
    assert ("credential-url", "url.query.X-Amz-Signature", "error") in issues
    messages = " ".join(issue.message for issue in result.issues)
    assert "hidden-token" not in messages
    assert "hidden-signature" not in messages
    assert "hidden-password" not in messages
