from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.shared.json import to_jsonable


class HarnessWorkerStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    WAITING_APPROVAL = "waiting_approval"


FORBIDDEN_WORKER_RESULT_KEYS = frozenset(
    {
        "next_step",
        "next_route",
        "route",
        "route_to",
        "route_to_repair",
        "routing_decision",
        "retry",
        "replan",
        "halt_workflow",
        "complete_run",
        "quality_passed",
        "quality_score",
        "quality_verdict",
        "approval_decision",
        "approval_granted",
        "approval_status",
        "approved",
        "authorize",
        "authorization_decision",
        "tool_authorization",
        "tool_authorized",
        "write_memory",
        "memory_write",
        "memory_write_allowed",
        "memory_write_decision",
        "should_write_memory",
        "accept",
        "accepted",
        "publish",
        "publish_artifact",
        "publication_approved",
        "publication_decision",
        "should_publish",
        "promote_skill",
        "skip_eval",
        "auto_promote",
        "active",
    }
)


@dataclass(frozen=True)
class HarnessWorkerResult:
    status: HarnessWorkerStatus | str
    output: dict[str, Any] = field(default_factory=dict)
    artifacts: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", HarnessWorkerStatus(self.status))
        output = dict(self.output)
        forbidden = sorted(FORBIDDEN_WORKER_RESULT_KEYS.intersection(output))
        if forbidden:
            raise HarnessValidationError(
                "worker result output must not contain flow-control fields",
                details={"forbidden": forbidden},
            )
        object.__setattr__(self, "output", output)
        object.__setattr__(self, "artifacts", tuple(str(ref) for ref in self.artifacts))
        object.__setattr__(self, "diagnostics", dict(self.diagnostics))
        object.__setattr__(self, "metrics", dict(self.metrics))

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "output": to_jsonable(self.output),
            "artifacts": list(self.artifacts),
            "diagnostics": to_jsonable(self.diagnostics),
            "metrics": to_jsonable(self.metrics),
            "error": self.error,
        }


__all__ = ["FORBIDDEN_WORKER_RESULT_KEYS", "HarnessWorkerResult", "HarnessWorkerStatus"]
