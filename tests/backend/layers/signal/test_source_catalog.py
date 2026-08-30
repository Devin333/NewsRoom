from backend.layers.signal.source_catalog import (
    SOURCE_CATEGORIES,
    SOURCE_PRIORITIES,
    SOURCE_SIGNAL_KINDS,
    SOURCE_TRUST_POLICIES,
    is_valid_source_category,
    is_valid_source_priority,
    normalize_source_category,
    normalize_source_priority,
)


def test_source_catalog_exposes_final_categories() -> None:
    assert SOURCE_CATEGORIES == (
        "research",
        "open_source",
        "model_platform",
        "official_blog",
        "agent_framework",
        "developer_discussion",
        "engineering_practice",
    )
    assert "chinese_ai_media" not in SOURCE_CATEGORIES


def test_source_catalog_validates_and_normalizes_values() -> None:
    assert normalize_source_category("Official-Blog") == "official_blog"
    assert normalize_source_category("developer discussion") == "developer_discussion"
    assert is_valid_source_category("research") is True
    assert is_valid_source_category("community") is False
    assert is_valid_source_category("chinese_ai_media") is False

    assert SOURCE_PRIORITIES == ("p0", "p1", "p2", "p3")
    assert normalize_source_priority(" P1 ") == "p1"
    assert is_valid_source_priority("p2") is True
    assert is_valid_source_priority("p4") is False


def test_source_catalog_includes_signal_and_trust_terms() -> None:
    assert "paper" in SOURCE_SIGNAL_KINDS
    assert "model_release" in SOURCE_SIGNAL_KINDS
    assert "engineering_case" in SOURCE_SIGNAL_KINDS
    assert "official" in SOURCE_TRUST_POLICIES
    assert "low_confidence" in SOURCE_TRUST_POLICIES
