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
