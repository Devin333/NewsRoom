from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from hashlib import sha256
from typing import Any

from domain.sources import RawSourceItem, SourceDefinition, SourceError
from sources.connectors.metadata import source_item_metadata


class ManualConnector:
    def fetch(
        self,
        source: SourceDefinition,
        *,
        records: Sequence[dict[str, Any]] | None = None,
        limit: int | None = None,
    ) -> tuple[list[RawSourceItem], list[SourceError]]:
        try:
            items = self.parse(
                source,
                records if records is not None else _records_from_source(source),
                limit=limit,
            )
        except Exception as exc:
            return [], [_exception_source_error(source, exc)]

        if not items:
            return [], [
                _source_error(
                    source,
                    "empty_manual_source",
                    "manual source contained no records",
                    metadata={"phase": "parse", "retryable": False, "source_health_affecting": False},
                )
            ]
        return items, []

    def parse(
        self,
        source: SourceDefinition,
        records: Sequence[dict[str, Any]],
        *,
        limit: int | None = None,
    ) -> list[RawSourceItem]:
        raw_items = [
            _raw_item(source=source, record=record, index=index)
            for index, record in enumerate(records)
        ]
        return raw_items[:limit] if limit else raw_items


def _records_from_source(source: SourceDefinition) -> Sequence[dict[str, Any]]:
    records = source.metadata.get("records", [])
    if not isinstance(records, list):
        raise ValueError("manual source metadata.records must be a list")
    return records


def _raw_item(*, source: SourceDefinition, record: dict[str, Any], index: int) -> RawSourceItem:
    if not isinstance(record, dict):
        raise ValueError("manual source record must be an object")
    title = _required_text(record.get("title"), "title")
    url = _required_text(record.get("url"), "url")
    metadata = source_item_metadata(source)
    metadata.update(dict(record.get("metadata") or {}))
    metadata.update(
        {
            "manual_record_index": index,
        }
    )
    for key in ("submitted_by", "reviewer_score"):
        if key in record:
            metadata[key] = record[key]
    item_hash = sha256(f"{source.source_id}|{url}|{title}".encode("utf-8")).hexdigest()
    return RawSourceItem(
        source_item_id=f"raw_{item_hash[:16]}",
        source_id=source.source_id,
        source_name=source.name,
        source_type=source.source_type,
        title=title,
        url=url,
        fetched_at=datetime.now(UTC),
        published_at=_parse_datetime(_optional_text(record.get("published_at"))),
        summary=_optional_text(record.get("summary")),
        raw_content=_optional_text(record.get("raw_content")),
        authors=_string_list(record.get("authors")),
        tags=_string_list(record.get("tags")),
        language=_optional_text(record.get("language")) or source.language,
        metadata=metadata,
    )


def _required_text(value: Any, field_name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise ValueError(f"manual source record {field_name} is required")
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("manual source record list fields must be arrays")
    return [str(item).strip() for item in value if str(item).strip()]


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except (TypeError, ValueError):
        pass
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except ValueError:
        return None


def _source_error(
    source: SourceDefinition,
    error_type: str,
    error_message: str,
    *,
    metadata: dict[str, object] | None = None,
) -> SourceError:
    return SourceError(
        source_id=source.source_id,
        error_type=error_type,
        error_message=error_message,
        url=source.url,
        metadata=metadata or {},
    )


def _exception_source_error(source: SourceDefinition, exc: Exception) -> SourceError:
    return _source_error(
        source,
        "parse_error",
        str(exc),
        metadata={
            "phase": "parse",
            "original_exception_type": type(exc).__name__,
            "retryable": False,
            "source_health_affecting": False,
        },
    )
