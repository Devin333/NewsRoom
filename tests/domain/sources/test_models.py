import pytest

from domain.sources import SourceDefinition, SourceReliability, SourceType


def test_source_definition_normalizes_enums() -> None:
    source = SourceDefinition(
        source_id="openai",
        name="OpenAI",
        source_type="rss",
        url="https://example.com/feed.xml",
        reliability="high",
    )

    assert source.source_type == SourceType.RSS
    assert source.reliability == SourceReliability.HIGH


def test_source_definition_requires_url() -> None:
    with pytest.raises(ValueError, match="url"):
        SourceDefinition(source_id="bad", name="Bad", source_type="rss", url="")
