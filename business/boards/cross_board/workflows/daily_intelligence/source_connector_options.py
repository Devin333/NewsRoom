from __future__ import annotations

from typing import Any

from pydantic import Field

from business.foundation import PrimitiveModel
from business.foundation.models.source import SourceDefinition, SourceType


class ManualSourceRecords(PrimitiveModel):
    schema_version: str = "business.cross_board.daily_source_connector.manual_records.v1"
    records: list[Any] = Field(default_factory=list)


class SourceConnectorRuntimeOptions(PrimitiveModel):
    schema_version: str = "business.cross_board.daily_source_connector.options.v1"
    source_id: str
    source_type: SourceType
    request_topic: str | None = None
    query: str | None = None
    manual_records: ManualSourceRecords | None = None
    repository: str | None = None
    github_mode: str | None = None
    story_list: str | None = None
    subreddit: str | None = None
    listing: str | None = None
    time_range: str | None = None
    tag: str | None = None
    site: str | None = None

    @classmethod
    def from_source(
        cls,
        source: SourceDefinition,
        *,
        request: dict[str, Any],
    ) -> "SourceConnectorRuntimeOptions":
        metadata = dict(source.metadata or {})
        request_topic = _optional_text(request.get("topic"))
        source_type = SourceType(source.source_type)
        query = _connector_query(source_type, metadata=metadata, request_topic=request_topic)
        return cls(
            source_id=source.source_id,
            source_type=source_type,
            request_topic=request_topic,
            query=query,
            manual_records=_connector_manual_records(source_type, metadata=metadata),
            repository=_optional_text(metadata.get("repository")),
            github_mode=_connector_github_mode(source_type, metadata=metadata),
            story_list=_optional_text(metadata.get("story_list")),
            subreddit=_optional_text(metadata.get("subreddit")),
            listing=_optional_text(metadata.get("listing")),
            time_range=_connector_time_range(source_type, metadata=metadata),
            tag=_connector_tag(source_type, metadata=metadata),
            site=_optional_text(metadata.get("site")),
        )


def _connector_query(
    source_type: SourceType,
    *,
    metadata: dict[str, Any],
    request_topic: str | None,
) -> str | None:
    metadata_query = _optional_text(metadata.get("query"))
    if source_type in {SourceType.ARXIV, SourceType.GITHUB}:
        return metadata_query or request_topic
    return metadata_query


def _connector_manual_records(source_type: SourceType, *, metadata: dict[str, Any]) -> ManualSourceRecords | None:
    if source_type != SourceType.MANUAL or "records" not in metadata:
        return None
    records = metadata.get("records")
    if not isinstance(records, list):
        return None
    return ManualSourceRecords(records=list(records))


def _connector_tag(source_type: SourceType, *, metadata: dict[str, Any]) -> str | None:
    if source_type == SourceType.STACKOVERFLOW:
        return _optional_text(metadata.get("tagged")) or _optional_text(metadata.get("tag"))
    return _optional_text(metadata.get("tag"))


def _connector_github_mode(source_type: SourceType, *, metadata: dict[str, Any]) -> str | None:
    if source_type != SourceType.GITHUB:
        return None
    return _optional_text(metadata.get("github_mode")) or _optional_text(metadata.get("mode"))


def _connector_time_range(source_type: SourceType, *, metadata: dict[str, Any]) -> str | None:
    if source_type != SourceType.REDDIT:
        return None
    return _optional_text(metadata.get("time_range")) or _optional_text(metadata.get("time"))


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = ["ManualSourceRecords", "SourceConnectorRuntimeOptions"]
