from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.framework.artifacts import ArtifactManager
from core.framework.tools.models import ToolDefinition
from core.framework.tools.registry import ToolRegistry


def register_artifact_tools(
    registry: ToolRegistry,
    *,
    artifact_manager: ArtifactManager,
    run_id: str,
) -> None:
    registry.register(
        ToolDefinition(
            name="artifact.write",
            description="Write a JSON or text artifact under the current run directory.",
            input_schema={
                "required": ["path", "content"],
                "properties": {
                    "path": {"type": "string"},
                    "content": {
                        "type": ["object", "array", "string", "number", "boolean", "null"]
                    },
                    "content_type": {
                        "type": "string",
                        "enum": ["application/json", "text/plain"],
                    },
                },
                "additionalProperties": False,
            },
            side_effect="writes_local_state",
        ),
        lambda args: _write_artifact(artifact_manager, run_id, args),
    )
    registry.register(
        ToolDefinition(
            name="artifact.load",
            description="Load a JSON or text artifact from the current run directory.",
            input_schema={
                "required": ["path"],
                "properties": {
                    "path": {"type": "string"},
                    "content_type": {
                        "type": "string",
                        "enum": ["application/json", "text/plain"],
                    },
                },
                "additionalProperties": False,
            },
            side_effect="read_only",
            concurrency_safe=True,
        ),
        lambda args: _load_artifact(artifact_manager, run_id, args),
    )


def _write_artifact(
    artifact_manager: ArtifactManager,
    run_id: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    relative_path = str(args["path"])
    content = args["content"]
    content_type = str(args.get("content_type") or _content_type_for(content))
    if content_type == "text/plain":
        target = artifact_manager.write_text(run_id, relative_path, str(content))
    else:
        target = artifact_manager.write_json(run_id, relative_path, content)
    return _artifact_payload(relative_path, content_type, target)


def _load_artifact(
    artifact_manager: ArtifactManager,
    run_id: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    relative_path = str(args["path"])
    target = _artifact_path(artifact_manager, run_id, relative_path)
    content_type = str(args.get("content_type") or _content_type_for_path(target))
    text = target.read_text(encoding="utf-8")
    content = json.loads(text) if content_type == "application/json" else text
    payload = _artifact_payload(relative_path, content_type, target)
    payload["content"] = content
    return payload


def _artifact_path(artifact_manager: ArtifactManager, run_id: str, relative_path: str) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"artifact path must be relative to the run directory: {relative_path}")
    return artifact_manager.run_dir(run_id) / relative


def _artifact_payload(relative_path: str, content_type: str, target: Path) -> dict[str, Any]:
    return {
        "artifact_id": f"artifact:{relative_path}",
        "relative_path": relative_path,
        "content_type": content_type,
        "size_bytes": target.stat().st_size,
    }


def _content_type_for(content: Any) -> str:
    return "text/plain" if isinstance(content, str) else "application/json"


def _content_type_for_path(path: Path) -> str:
    return "application/json" if path.suffix.lower() == ".json" else "text/plain"
