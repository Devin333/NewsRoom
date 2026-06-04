from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.state import HarnessState
from framework.shared.json import stable_json_dumps, to_jsonable
from framework.shared.time import format_datetime, utc_now


@dataclass(frozen=True)
class HarnessCheckpoint:
    checkpoint_id: str
    run_id: str
    state: HarnessState
    last_event_id: str | None = None
    checksum: str | None = None
    artifact_refs: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: Any = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not str(self.checkpoint_id).strip():
            raise HarnessValidationError("checkpoint_id is required")
        if not str(self.run_id).strip():
            raise HarnessValidationError("run_id is required")
        if not isinstance(self.state, HarnessState):
            raise HarnessValidationError("state must be HarnessState")
        if self.state.run_spec.run_id != self.run_id:
            raise HarnessValidationError("checkpoint run_id must match state run_id")
        checksum = self.checksum or checkpoint_checksum(self.run_id, self.state.to_dict(), self.last_event_id)
        object.__setattr__(self, "checkpoint_id", str(self.checkpoint_id))
        object.__setattr__(self, "run_id", str(self.run_id))
        object.__setattr__(self, "checksum", checksum)
        object.__setattr__(self, "artifact_refs", tuple(str(ref) for ref in self.artifact_refs))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "run_id": self.run_id,
            "state": self.state.to_dict(),
            "last_event_id": self.last_event_id,
            "checksum": self.checksum,
            "artifact_refs": list(self.artifact_refs),
            "metadata": to_jsonable(self.metadata),
            "created_at": format_datetime(self.created_at),
        }


def checkpoint_checksum(run_id: str, state_payload: dict[str, Any], last_event_id: str | None) -> str:
    import hashlib

    payload = {"run_id": run_id, "state": state_payload, "last_event_id": last_event_id}
    return f"sha256:{hashlib.sha256(stable_json_dumps(payload).encode()).hexdigest()}"


__all__ = ["HarnessCheckpoint", "checkpoint_checksum"]
