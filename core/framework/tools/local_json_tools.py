from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from core.framework.tools.models import ToolDefinition
from core.framework.tools.registry import ToolRegistry


_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


def register_local_json_tools(
    registry: ToolRegistry,
    *,
    root: str | Path,
) -> None:
    store = LocalJsonToolStore(root)
    registry.register(
        ToolDefinition(
            name="local_json.save",
            description="Save a scoped JSON record under the configured local JSON root.",
            input_schema={
                "required": ["collection", "record_id", "value"],
                "properties": {
                    "collection": {"type": "string"},
                    "record_id": {"type": "string"},
                    "value": {
                        "type": ["object", "array", "string", "number", "boolean", "null"]
                    },
                    "metadata": {"type": "object"},
                },
                "additionalProperties": False,
            },
            side_effect="writes_local_state",
            concurrency_safe=False,
            max_result_bytes=100_000,
            metadata={"writes_local_json": True},
        ),
        lambda args: _save_local_json(args, store=store),
    )


class LocalJsonToolStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def save(self, *, collection: str, record_id: str, value: Any, metadata: dict[str, Any]) -> Path:
        collection_name = _safe_name(collection, "collection")
        record_name = _safe_name(record_id, "record_id")
        target = self.root / collection_name / f"{record_name}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "collection": collection_name,
            "record_id": record_name,
            "value": value,
            "metadata": dict(metadata),
        }
        with target.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        return target


def _save_local_json(args: dict[str, Any], *, store: LocalJsonToolStore) -> dict[str, Any]:
    metadata = args.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")
    collection = str(args["collection"])
    record_id = str(args["record_id"])
    target = store.save(
        collection=collection,
        record_id=record_id,
        value=args["value"],
        metadata=dict(metadata),
    )
    return {
        "saved": True,
        "collection": _safe_name(collection, "collection"),
        "record_id": _safe_name(record_id, "record_id"),
        "relative_path": target.relative_to(store.root).as_posix(),
        "size_bytes": target.stat().st_size,
    }


def _safe_name(value: str, field_name: str) -> str:
    name = value.strip()
    if not name:
        raise ValueError(f"{field_name} is required")
    if "/" in name or "\\" in name or ".." in Path(name).parts or not _SAFE_NAME.fullmatch(name):
        raise ValueError(f"{field_name} must be a safe record name")
    return name
