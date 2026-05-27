from __future__ import annotations

import json
import os
import sys
from typing import Any


DEFAULT_COLLECTIONS = [
    "source_chunks",
    "evidence_items",
    "report_sections",
    "topic_summaries",
    "agent_memories",
]

DEFAULT_PAYLOAD_INDEXES = [
    "run_id",
    "report_id",
    "topic",
    "source_type",
    "category",
    "published_at",
    "confidence",
    "language",
]


def main() -> int:
    url = os.environ.get("NEWS_QDRANT_URL")
    if not url:
        _emit(
            status="skipped",
            service="qdrant",
            reason="NEWS_QDRANT_URL is not set",
        )
        return 0

    try:
        from qdrant_client import QdrantClient
    except ModuleNotFoundError as exc:
        _emit(
            status="unready",
            service="qdrant",
            reason=f"missing dependency: {exc.name}",
        )
        return 0

    try:
        client = QdrantClient(url=url, timeout=int(_timeout_seconds()))
        collections = _collections_from_env()
        collection_statuses = [
            {
                "collection": collection,
                "exists": bool(client.collection_exists(collection)),
            }
            for collection in collections
        ]
        payload_index_statuses = [
            _payload_index_status(client, collection, _payload_indexes_from_env())
            for collection in collections
            if bool(client.collection_exists(collection))
        ]
    except Exception as exc:
        _emit(
            status="unready",
            service="qdrant",
            reason=f"{exc.__class__.__name__}: {exc}",
        )
        return 0

    missing = [item["collection"] for item in collection_statuses if not item["exists"]]
    missing_payload_indexes = [
        item
        for collection in payload_index_statuses
        for item in collection["missing_payload_indexes"]
    ]
    status = "ready" if not missing and not missing_payload_indexes else "unready"
    if missing:
        reason = "required collections are missing"
    elif missing_payload_indexes:
        reason = "required payload indexes are missing"
    else:
        reason = None
    _emit(
        status=status,
        service="qdrant",
        reason=reason,
        url=url,
        collections=collection_statuses,
        payload_indexes=payload_index_statuses,
        missing_collections=missing,
        missing_payload_indexes=missing_payload_indexes,
    )
    return 0


def _collections_from_env() -> list[str]:
    raw = os.environ.get("NEWS_QDRANT_CHECK_COLLECTIONS")
    if not raw:
        return list(DEFAULT_COLLECTIONS)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _payload_indexes_from_env() -> list[str]:
    raw = os.environ.get("NEWS_QDRANT_CHECK_PAYLOAD_INDEXES")
    if not raw:
        return list(DEFAULT_PAYLOAD_INDEXES)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _payload_index_status(client: Any, collection: str, required_fields: list[str]) -> dict[str, Any]:
    existing = _existing_payload_indexes(client, collection)
    missing = sorted(set(required_fields) - existing)
    return {
        "collection": collection,
        "checked_payload_indexes": sorted(required_fields),
        "existing_payload_indexes": sorted(existing),
        "missing_payload_indexes": [
            {"collection": collection, "field_name": field_name}
            for field_name in missing
        ],
    }


def _existing_payload_indexes(client: Any, collection: str) -> set[str]:
    try:
        info = client.get_collection(collection)
    except Exception:
        return set()
    payload_schema = getattr(info, "payload_schema", None)
    if isinstance(payload_schema, dict):
        return {str(key) for key in payload_schema}
    return set()


def _timeout_seconds() -> float:
    value = os.environ.get("NEWS_QDRANT_CHECK_TIMEOUT_SECONDS", "3")
    try:
        timeout = float(value)
    except ValueError:
        return 3.0
    return max(0.1, timeout)


def _emit(**payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    sys.exit(main())
