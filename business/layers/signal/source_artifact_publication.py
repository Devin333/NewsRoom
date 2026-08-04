from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from framework.agent.artifacts import ArtifactManager

from business.layers.signal.artifacts import SourceArtifactWriter


SOURCE_ARTIFACT_INDEX_KEY = "source_artifacts"
SOURCE_ARTIFACT_INDEX_PATH = "source_artifacts/index.json"


@dataclass(frozen=True)
class SourceArtifactPublication:
    index: dict[str, Any]
    manifest_summary: dict[str, Any]


class SourceArtifactPublicationService:
    def __init__(self, artifact_manager: ArtifactManager) -> None:
        self._writer = SourceArtifactWriter(artifact_manager)

    def publish(
        self,
        run_id: str,
        *,
        raw_items: Any = None,
        source_fetch_requests: Any = None,
        source_fetch_results: Any = None,
        source_errors: Any = None,
    ) -> SourceArtifactPublication | None:
        index = self._writer.write_source_artifacts(
            run_id,
            raw_items=raw_items,
            source_fetch_requests=source_fetch_requests,
            source_fetch_results=source_fetch_results,
            source_errors=source_errors,
        )
        if index is None:
            return None
        return SourceArtifactPublication(
            index=index,
            manifest_summary=source_artifact_manifest_summary(index),
        )


def source_artifact_manifest_summary(index: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "item_count": _int_count(index.get("item_count")),
        "error_count": _int_count(index.get("error_count")),
        "raw_content_count": _int_count(index.get("raw_content_count")),
        "fetch_request_count": _int_count(index.get("fetch_request_count")),
        "fetch_result_count": _int_count(index.get("fetch_result_count")),
        "total_count": _entry_count(index.get("entries")),
    }
    _add_optional_count(summary, index, "response_headers_count")
    _add_optional_count(summary, index, "parsed_items_count")
    return summary


def _add_optional_count(
    summary: dict[str, Any],
    index: Mapping[str, Any],
    key: str,
) -> None:
    count = _int_count(index.get(key))
    if count:
        summary[key] = count


def _entry_count(value: Any) -> int:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return len(value)
    return 0


def _int_count(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


__all__ = [
    "SOURCE_ARTIFACT_INDEX_KEY",
    "SOURCE_ARTIFACT_INDEX_PATH",
    "SourceArtifactPublication",
    "SourceArtifactPublicationService",
    "source_artifact_manifest_summary",
]
