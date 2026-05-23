from pathlib import Path

from business.layers.signal.source_config import load_source_registry
from business.layers.signal.source_catalog import SOURCE_CATEGORIES


def test_tracked_ai_community_source_config_uses_final_taxonomy() -> None:
    registry = load_source_registry(Path("configs/sources.yaml"))
    sources = registry.list_sources(enabled_only=False)
    categories = {source.category for source in sources}

    assert len(sources) >= 30
    assert categories <= set(SOURCE_CATEGORIES)
    assert "chinese_ai_media" not in categories
    assert "community" not in categories
    assert "official" not in categories
    assert registry.validate().is_valid is True


def test_chinese_sources_are_mapped_by_language_and_region() -> None:
    registry = load_source_registry(Path("configs/sources.yaml"))
    chinese_sources = [
        source
        for source in registry.list_sources(enabled_only=False)
        if source.language == "zh" or source.region == "cn"
    ]

    assert chinese_sources
    assert all(source.category in SOURCE_CATEGORIES for source in chinese_sources)
    assert all(source.category != "chinese_ai_media" for source in chinese_sources)
    assert {source.region for source in chinese_sources} == {"cn"}


def test_tracked_sources_have_priority_group_and_signal_kind_metadata() -> None:
    registry = load_source_registry(Path("configs/sources.yaml"))

    for source in registry.list_sources(enabled_only=False):
        assert source.metadata.get("group") == source.category
        assert source.metadata.get("priority") in {"p0", "p1", "p2", "p3"}
        assert isinstance(source.metadata.get("signal_kind"), str)
