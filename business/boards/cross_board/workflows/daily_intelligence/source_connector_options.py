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
    github_discussion_category: str | None = None
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
        metadata = SourceConnectorMetadataView.from_source(source)
        request_topic = _optional_text(request.get("topic"))
        source_type = SourceType(source.source_type)
        query = _connector_query(source_type, metadata=metadata, request_topic=request_topic)
        return cls(
            source_id=source.source_id,
            source_type=source_type,
            request_topic=request_topic,
            query=query,
            manual_records=_connector_manual_records(source_type, metadata=metadata),
            repository=metadata.repository,
            github_mode=_connector_github_mode(source_type, metadata=metadata),
            github_discussion_category=_connector_github_discussion_category(
                source_type,
                metadata=metadata,
            ),
            story_list=metadata.story_list,
            subreddit=metadata.subreddit,
            listing=metadata.listing,
            time_range=_connector_time_range(source_type, metadata=metadata),
            tag=_connector_tag(source_type, metadata=metadata),
            site=metadata.site,
        )


class SourceConnectorMetadataView(PrimitiveModel):
    schema_version: str = "business.cross_board.daily_source_connector.metadata_view.v1"
    values: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_source(cls, source: SourceDefinition) -> "SourceConnectorMetadataView":
        return cls(values=dict(source.metadata or {}))

    @property
    def query(self) -> str | None:
        return self.text("query")

    @property
    def repository(self) -> str | None:
        return self.text("repository")

    @property
    def github_mode(self) -> str | None:
        return self.text("github_mode")

    @property
    def github_discussion_category(self) -> str | None:
        return self.text("discussion_category")

    @property
    def story_list(self) -> str | None:
        return self.text("story_list")

    @property
    def subreddit(self) -> str | None:
        return self.text("subreddit")

    @property
    def listing(self) -> str | None:
        return self.text("listing")

    @property
    def reddit_time_range(self) -> str | None:
        return self.text("time_range") or self.text("time")

    @property
    def tag(self) -> str | None:
        return self.text("tag")

    @property
    def stackoverflow_tag(self) -> str | None:
        return self.text("tagged") or self.text("tag")

    @property
    def site(self) -> str | None:
        return self.text("site")

    @property
    def manual_records(self) -> ManualSourceRecords | None:
        records = self.values.get("records")
        if not isinstance(records, list):
            return None
        return ManualSourceRecords(records=list(records))

    def text(self, key: str) -> str | None:
        return _optional_text(self.values.get(key))


def _connector_query(
    source_type: SourceType,
    *,
    metadata: SourceConnectorMetadataView,
    request_topic: str | None,
) -> str | None:
    if source_type in {SourceType.ARXIV, SourceType.GITHUB}:
        return metadata.query or request_topic
    return metadata.query


def _connector_manual_records(
    source_type: SourceType,
    *,
    metadata: SourceConnectorMetadataView,
) -> ManualSourceRecords | None:
    if source_type != SourceType.MANUAL:
        return None
    return metadata.manual_records


def _connector_tag(
    source_type: SourceType,
    *,
    metadata: SourceConnectorMetadataView,
) -> str | None:
    if source_type == SourceType.STACKOVERFLOW:
        return metadata.stackoverflow_tag
    return metadata.tag


def _connector_github_mode(
    source_type: SourceType,
    *,
    metadata: SourceConnectorMetadataView,
) -> str | None:
    if source_type != SourceType.GITHUB:
        return None
    return metadata.github_mode


def _connector_github_discussion_category(
    source_type: SourceType,
    *,
    metadata: SourceConnectorMetadataView,
) -> str | None:
    if source_type != SourceType.GITHUB:
        return None
    return metadata.github_discussion_category


def _connector_time_range(
    source_type: SourceType,
    *,
    metadata: SourceConnectorMetadataView,
) -> str | None:
    if source_type != SourceType.REDDIT:
        return None
    return metadata.reddit_time_range


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = [
    "ManualSourceRecords",
    "SourceConnectorMetadataView",
    "SourceConnectorRuntimeOptions",
]
