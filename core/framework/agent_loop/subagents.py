from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from core.framework.tools.redaction import redact_sensitive_values


class SubAgentStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class SubAgentTask:
    parent_agent_id: str
    child_agent_id: str
    task: str
    inputs: dict[str, Any] = field(default_factory=dict)
    handoff_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, *, redact: bool = True) -> dict[str, Any]:
        inputs = dict(self.inputs)
        metadata = dict(self.metadata)
        return {
            "parent_agent_id": self.parent_agent_id,
            "child_agent_id": self.child_agent_id,
            "task": self.task,
            "inputs": redact_sensitive_values(inputs) if redact else inputs,
            "handoff_reason": self.handoff_reason,
            "metadata": redact_sensitive_values(metadata) if redact else metadata,
        }


@dataclass(frozen=True)
class SubAgentResult:
    child_agent_id: str
    success: bool
    status: SubAgentStatus | str = SubAgentStatus.SUCCEEDED
    output: dict[str, Any] = field(default_factory=dict)
    summary: str | None = None
    error: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    artifact_refs: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, *, redact: bool = True) -> dict[str, Any]:
        output = dict(self.output)
        events = [dict(event) for event in self.events]
        metrics = dict(self.metrics)
        artifact_refs = [dict(ref) for ref in self.artifact_refs]
        metadata = dict(self.metadata)
        payload = {
            "child_agent_id": self.child_agent_id,
            "success": self.success,
            "status": _status_value(self.status),
            "output": output,
            "summary": self.summary,
            "error": self.error,
            "events": events,
            "metrics": metrics,
            "artifact_refs": artifact_refs,
            "metadata": metadata,
        }
        return redact_sensitive_values(payload) if redact else payload


class SubAgentExecutor(Protocol):
    def run(self, task: SubAgentTask) -> SubAgentResult:
        """Run a child agent against a read-only parent snapshot."""


def _status_value(status: SubAgentStatus | str) -> str:
    return status.value if isinstance(status, SubAgentStatus) else str(status)
