from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Sequence

from framework.workflow.runtime.manifest import (
    REQUIRED_RUN_ARTIFACTS,
    validate_run_manifest,
)


_FAILED_TERMINAL_STATUSES = {
    "failed",
    "blocked",
    "budget_exceeded",
    "cancelled",
}
_PAUSED_TERMINAL_STATUSES = {"paused", "waiting_for_human"}


@dataclass(frozen=True)
class CanonicalWorkflowRunFixture:
    root: Path
    run_dir: Path
    manifest_path: Path
    manifest: dict[str, Any]

    def artifact_path(self, artifact_key: str) -> Path:
        return self.run_dir / self.manifest["artifacts"][artifact_key]


def write_canonical_terminal_run(
    root: str | Path,
    run_id: str = "run-1",
    *,
    status: str = "succeeded",
    workflow_id: str = "daily",
    workflow_version: str = "1.0",
    profile: str = "live-offline",
    events: Sequence[Mapping[str, Any]] | None = None,
    manifest_output: Mapping[str, Any] | None = None,
    terminal_content: Any | None = None,
    extra_artifacts: Mapping[str, tuple[str, bytes]] | None = None,
) -> CanonicalWorkflowRunFixture:
    """Write a production-shaped terminal run whose manifest passes strict validation."""

    artifact_root = Path(root)
    run_dir = artifact_root / run_id
    run_dir.mkdir(parents=True)

    actual_events = list(events) if events is not None else [
        {
            "event_type": "workflow_started",
            "run_id": run_id,
            "occurred_at": "2026-05-14T01:00:00Z",
            "payload": {"profile": profile},
        },
        {
            "event_type": f"workflow_{status}",
            "run_id": run_id,
            "occurred_at": "2026-05-14T01:00:01Z",
            "payload": {},
        },
    ]
    events_bytes = b"".join(_json_bytes(event) + b"\n" for event in actual_events)
    step_status = "succeeded" if status == "succeeded" else status
    artifact_contents: dict[str, tuple[str, bytes]] = {
        "request": (
            REQUIRED_RUN_ARTIFACTS["request"],
            _json_bytes({"request_id": "request-1", "query": "fixture query"}),
        ),
        "workflow_spec": (
            REQUIRED_RUN_ARTIFACTS["workflow_spec"],
            _json_bytes(
                {
                    "workflow_id": workflow_id,
                    "version": workflow_version,
                    "steps": [{"step_id": "write", "step_type": "transform"}],
                }
            ),
        ),
        "workflow_version": (
            REQUIRED_RUN_ARTIFACTS["workflow_version"],
            _json_bytes(
                {
                    "workflow_id": workflow_id,
                    "workflow_version": workflow_version,
                }
            ),
        ),
        "events": (REQUIRED_RUN_ARTIFACTS["events"], events_bytes),
        "data_buffer_snapshot": (
            REQUIRED_RUN_ARTIFACTS["data_buffer_snapshot"],
            _json_bytes({"report": "verified"}),
        ),
        "data_buffer_initial": (
            REQUIRED_RUN_ARTIFACTS["data_buffer_initial"],
            _json_bytes({}),
        ),
        "data_buffer_final": (
            REQUIRED_RUN_ARTIFACTS["data_buffer_final"],
            _json_bytes({"report": "verified"}),
        ),
        "data_buffer_diff": (
            REQUIRED_RUN_ARTIFACTS["data_buffer_diff"],
            _json_bytes({"added": {"report": "verified"}, "removed": {}, "changed": {}}),
        ),
        "step_results": (
            REQUIRED_RUN_ARTIFACTS["step_results"],
            _json_bytes(
                {
                    "write": {
                        "status": step_status,
                        "outputs": {"report": "verified"},
                    }
                }
            ),
        ),
        "metrics": (
            REQUIRED_RUN_ARTIFACTS["metrics"],
            _json_bytes({"step_count": 1, "event_count": len(actual_events)}),
        ),
        "redaction_report": (
            REQUIRED_RUN_ARTIFACTS["redaction_report"],
            _json_bytes({"redacted_count": 0, "fields": []}),
        ),
    }

    terminal_key, terminal_path = _terminal_artifact(status)
    actual_terminal_content = terminal_content
    if actual_terminal_content is None:
        if terminal_key == "output":
            actual_terminal_content = {
                "status": "ok",
                "result": "verified-original",
                "token": "fixture-secret-token",
            }
        elif terminal_key == "pause":
            actual_terminal_content = {"reason": "fixture pause"}
        else:
            actual_terminal_content = {"error_type": "FixtureFailure", "message": "fixture error"}
    artifact_contents[terminal_key] = (terminal_path, _json_bytes(actual_terminal_content))
    artifact_contents.update(dict(extra_artifacts or {}))

    artifacts = dict(REQUIRED_RUN_ARTIFACTS)
    artifacts[terminal_key] = terminal_path
    artifacts.update(
        {
            artifact_key: relative_path
            for artifact_key, (relative_path, _) in (extra_artifacts or {}).items()
        }
    )
    artifact_metadata = {
        artifact_key: {
            "checksum": sha256(content).hexdigest(),
            "content_type": _content_type(relative_path),
            "size_bytes": len(content),
        }
        for artifact_key, (relative_path, content) in artifact_contents.items()
    }
    artifact_metadata["manifest"] = {
        "checksum": "pending",
        "content_type": "application/json",
        "size_bytes": 0,
    }

    manifest: dict[str, Any] = {
        "schema_version": "newsroom.workflow_run_manifest.v1",
        "run_type": "workflow",
        "run_id": run_id,
        "workflow_id": workflow_id,
        "workflow_version": workflow_version,
        "profile": profile,
        "status": status,
        "started_at": "2026-05-14T01:00:00Z",
        "finished_at": "2026-05-14T01:00:01Z",
        "completed_at": "2026-05-14T01:00:01Z",
        "path": ["write"],
        "steps": {
            "write": {
                "status": step_status,
                "started_at": "2026-05-14T01:00:00Z",
                "finished_at": "2026-05-14T01:00:01Z",
                "outputs": {"report": "verified"},
            }
        },
        "artifacts": artifacts,
        "artifact_metadata": artifact_metadata,
        "artifact_refs": [],
        "artifact_index": [],
        "runner_versions": {},
        "checkpoints": [],
        "checkpoint_refs": [],
        "checkpoint_ref": None,
        "operations": [],
        "trace_id": None,
        "trace_ref": None,
        "gate_result_ref": None,
        "step_summaries": [{"step_id": "write", "status": step_status}],
        "step_artifacts": [],
        "warnings": [],
        "errors": [],
        "run_history_ref": None,
        "metrics": {"step_count": 1, "event_count": len(actual_events)},
        "step_count": 1,
        "event_count": len(actual_events),
        "output": dict(manifest_output or {"artifact_key": terminal_key}),
    }
    if terminal_key == "error":
        manifest["error"] = dict(actual_terminal_content)

    validate_run_manifest(manifest, require_terminal_artifact=True)
    for relative_path, content in artifact_contents.values():
        path = run_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    manifest_path = run_dir / REQUIRED_RUN_ARTIFACTS["manifest"]
    manifest_path.write_bytes(_json_bytes(manifest))
    return CanonicalWorkflowRunFixture(
        root=artifact_root,
        run_dir=run_dir,
        manifest_path=manifest_path,
        manifest=manifest,
    )


def rewrite_manifest(fixture: CanonicalWorkflowRunFixture, manifest: Mapping[str, Any]) -> None:
    fixture.manifest_path.write_bytes(_json_bytes(manifest))


def _terminal_artifact(status: str) -> tuple[str, str]:
    if status == "succeeded":
        return "output", "output.json"
    if status in _PAUSED_TERMINAL_STATUSES:
        return "pause", "pause.json"
    if status in _FAILED_TERMINAL_STATUSES:
        return "error", "error.json"
    raise ValueError(f"unsupported terminal fixture status: {status}")


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _content_type(relative_path: str) -> str:
    suffix = Path(relative_path).suffix.casefold()
    if suffix == ".json":
        return "application/json"
    if suffix == ".jsonl":
        return "application/x-ndjson"
    if suffix == ".md":
        return "text/markdown"
    if suffix == ".txt":
        return "text/plain"
    return "application/octet-stream"
