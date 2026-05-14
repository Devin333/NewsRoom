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
        client = QdrantClient(url=url, timeout=_timeout_seconds())
        collections = _collections_from_env()
        collection_statuses = [
            {
                "collection": collection,
                "exists": bool(client.collection_exists(collection)),
            }
            for collection in collections
        ]
    except Exception as exc:
        _emit(
            status="unready",
            service="qdrant",
            reason=f"{exc.__class__.__name__}: {exc}",
        )
        return 0

    missing = [item["collection"] for item in collection_statuses if not item["exists"]]
    status = "ready" if not missing else "unready"
    reason = None if not missing else "required collections are missing"
    _emit(
        status=status,
        service="qdrant",
        reason=reason,
        url=url,
        collections=collection_statuses,
        missing_collections=missing,
    )
    return 0


def _collections_from_env() -> list[str]:
    raw = os.environ.get("NEWS_QDRANT_CHECK_COLLECTIONS")
    if not raw:
        return list(DEFAULT_COLLECTIONS)
    return [item.strip() for item in raw.split(",") if item.strip()]


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
