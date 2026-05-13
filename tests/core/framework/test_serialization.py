import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from core.framework.artifacts import ArtifactManager
from core.framework.events import EventRecord
from core.framework.run_result import RunResult
from core.framework.serialization import to_json_safe
from core.framework.specs import WorkflowStatus


class _Route(Enum):
    ACCEPT = "accept"
    RETRY = "retry"


@dataclass(frozen=True)
class _NestedPayload:
    route: _Route
    created_at: datetime
    path: Path


class _DictLikePayload:
    def __init__(self, created_at: datetime) -> None:
        self._created_at = created_at

    def to_dict(self) -> dict[str, object]:
        return {
            "nested": _NestedPayload(
                route=_Route.RETRY,
                created_at=self._created_at,
                path=Path("runs/run-1/retry.json"),
            ),
            "levels": {2, 1},
        }


def test_to_json_safe_normalizes_nested_runtime_values() -> None:
    created_at = datetime(2026, 5, 13, 1, 2, 3, tzinfo=UTC)
    payload = {
        _Route.ACCEPT: {
            "created_at": created_at,
            "path": Path("runs/run-1/output.json"),
            "tuple": (_Route.RETRY, Path("runs/run-1/retry.json")),
            "set": {_Route.RETRY, _Route.ACCEPT},
            "dict_like": _DictLikePayload(created_at),
        },
        created_at: "datetime-key",
        Path("runs/run-1/manifest.json"): "path-key",
        7: "integer-key",
    }

    safe = to_json_safe(payload)

    assert safe["accept"]["created_at"] == "2026-05-13T01:02:03Z"
    assert safe["accept"]["path"] == "runs/run-1/output.json"
    assert safe["accept"]["tuple"] == ["retry", "runs/run-1/retry.json"]
    assert safe["accept"]["set"] == ["accept", "retry"]
    assert safe["accept"]["dict_like"]["nested"] == {
        "route": "retry",
        "created_at": "2026-05-13T01:02:03Z",
        "path": "runs/run-1/retry.json",
    }
    assert safe["accept"]["dict_like"]["levels"] == [1, 2]
    assert safe["2026-05-13T01:02:03Z"] == "datetime-key"
    assert safe["runs/run-1/manifest.json"] == "path-key"
    assert safe["7"] == "integer-key"
    json.dumps(safe, ensure_ascii=False, sort_keys=True)


def test_run_result_uses_shared_json_safe_serialization() -> None:
    created_at = datetime(2026, 5, 13, 1, 2, 3, tzinfo=UTC)
    result = RunResult(
        run_id="run-1",
        workflow_id="daily",
        workflow_version="1.0",
        status=WorkflowStatus.FAILED,
        output={
            "payload": _NestedPayload(
                route=_Route.ACCEPT,
                created_at=created_at,
                path=Path("runs/run-1/output.json"),
            ),
            _Route.RETRY: "retry-key",
        },
        error={"status": WorkflowStatus.FAILED, "at": created_at},
    )

    payload = result.to_dict()

    assert payload["status"] == "failed"
    assert payload["output"]["payload"] == {
        "route": "accept",
        "created_at": "2026-05-13T01:02:03Z",
        "path": "runs/run-1/output.json",
    }
    assert payload["output"]["retry"] == "retry-key"
    assert payload["error"] == {
        "status": "failed",
        "at": "2026-05-13T01:02:03Z",
    }
    json.dumps(payload, ensure_ascii=False, sort_keys=True)


def test_event_record_uses_shared_json_safe_serialization() -> None:
    created_at = datetime(2026, 5, 13, 1, 2, 3, tzinfo=UTC)
    event = EventRecord(
        run_id="run-1",
        event_type="step_succeeded",
        occurred_at=created_at,
        payload={"payload": _DictLikePayload(created_at)},
    )

    payload = event.to_dict()

    assert payload["occurred_at"] == "2026-05-13T01:02:03Z"
    assert payload["payload"]["payload"]["nested"]["route"] == "retry"
    assert payload["payload"]["payload"]["levels"] == [1, 2]
    json.dumps(payload, ensure_ascii=False, sort_keys=True)


def test_artifact_manager_writes_json_safe_payloads(tmp_path) -> None:
    created_at = datetime(2026, 5, 13, 1, 2, 3, tzinfo=UTC)
    manager = ArtifactManager(tmp_path)
    manager.start_run("run-1")

    path = manager.write_json(
        "run-1",
        "payload.json",
        {
            "payload": _NestedPayload(
                route=_Route.ACCEPT,
                created_at=created_at,
                path=Path("runs/run-1/output.json"),
            ),
            "routes": {_Route.RETRY, _Route.ACCEPT},
        },
    )

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "payload": {
            "route": "accept",
            "created_at": "2026-05-13T01:02:03Z",
            "path": "runs/run-1/output.json",
        },
        "routes": ["accept", "retry"],
    }
