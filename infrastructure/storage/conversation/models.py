from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from typing import Any
from uuid import uuid4

from framework.shared.graph_identity import (
    CONVERSATION_SCOPE_GRAPH,
    CONVERSATION_SCOPE_STANDALONE,
    ConversationMessageScope,
)


# v1 is the migration-only history schema and is never live-readable.
GRAPH_CONVERSATION_CURSOR_SCHEMA = "newsroom.graph-conversation-cursor/v2"
GRAPH_AGENT_ITERATION_CHECKPOINT_SCHEMA = (
    "newsroom.graph-agent-iteration-checkpoint/v2"
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class AgentMessageRecord:
    conversation_id: str
    role: str
    content: Any
    scope_kind: str
    message_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: datetime = field(default_factory=_utc_now)
    agent_id: str | None = None
    run_id: str | None = None
    graph_id: str | None = None
    graph_version: str | None = None
    graph_ref: str | None = None
    graph_checksum: str | None = None
    node_id: str | None = None
    node_instance_id: str | None = None
    graph_checkpoint_ref: str | None = None
    activity_id: str | None = None
    attempt: int | None = None
    redacted: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_message_scope(
            scope_kind=self.scope_kind,
            run_id=self.run_id,
            graph_id=self.graph_id,
            graph_version=self.graph_version,
            graph_ref=self.graph_ref,
            graph_checksum=self.graph_checksum,
            node_id=self.node_id,
            node_instance_id=self.node_instance_id,
            graph_checkpoint_ref=self.graph_checkpoint_ref,
            activity_id=self.activity_id,
            attempt=self.attempt,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "message_id": self.message_id,
            "conversation_id": self.conversation_id,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "scope_kind": self.scope_kind,
            "agent_id": self.agent_id,
            "run_id": self.run_id,
            "graph_id": self.graph_id,
            "graph_version": self.graph_version,
            "graph_ref": self.graph_ref,
            "graph_checksum": self.graph_checksum,
            "node_id": self.node_id,
            "node_instance_id": self.node_instance_id,
            "graph_checkpoint_ref": self.graph_checkpoint_ref,
            "activity_id": self.activity_id,
            "attempt": self.attempt,
            "redacted": self.redacted,
            "metadata": dict(self.metadata),
        }
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AgentMessageRecord:
        _require_exact_fields(
            payload,
            {
                "message_id",
                "conversation_id",
                "role",
                "content",
                "created_at",
                "scope_kind",
                "agent_id",
                "run_id",
                "graph_id",
                "graph_version",
                "graph_ref",
                "graph_checksum",
                "node_id",
                "node_instance_id",
                "graph_checkpoint_ref",
                "activity_id",
                "attempt",
                "redacted",
                "metadata",
            },
            "agent message",
        )
        return cls(
            message_id=str(payload["message_id"]),
            conversation_id=str(payload["conversation_id"]),
            role=str(payload["role"]),
            content=payload.get("content"),
            created_at=_parse_datetime(str(payload["created_at"])),
            scope_kind=str(payload["scope_kind"]),
            agent_id=_optional_str(payload.get("agent_id")),
            run_id=_optional_text(payload.get("run_id"), "run_id"),
            graph_id=_optional_text(payload.get("graph_id"), "graph_id"),
            graph_version=_optional_text(payload.get("graph_version"), "graph_version"),
            graph_ref=_optional_text(payload.get("graph_ref"), "graph_ref"),
            graph_checksum=_optional_text(payload.get("graph_checksum"), "graph_checksum"),
            node_id=_optional_text(payload.get("node_id"), "node_id"),
            node_instance_id=_optional_text(
                payload.get("node_instance_id"), "node_instance_id"
            ),
            graph_checkpoint_ref=_optional_text(
                payload.get("graph_checkpoint_ref"), "graph_checkpoint_ref"
            ),
            activity_id=_optional_text(payload.get("activity_id"), "activity_id"),
            attempt=_optional_int(payload.get("attempt")),
            redacted=bool(payload.get("redacted", True)),
            metadata=dict(payload.get("metadata") or {}),
        )


def message_scope_key(message: AgentMessageRecord) -> tuple[str, ...]:
    """Return the conversation-level identity that all messages must share."""
    if message.scope_kind == CONVERSATION_SCOPE_STANDALONE:
        return (CONVERSATION_SCOPE_STANDALONE,)
    return (
        CONVERSATION_SCOPE_GRAPH,
        str(message.run_id),
        str(message.graph_ref),
        str(message.graph_checksum),
    )


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("attempt must be an integer")
    return value


def _validate_message_scope(
    *,
    scope_kind: str,
    run_id: str | None,
    graph_id: str | None,
    graph_version: str | None,
    graph_ref: str | None,
    graph_checksum: str | None,
    node_id: str | None,
    node_instance_id: str | None,
    graph_checkpoint_ref: str | None,
    activity_id: str | None,
    attempt: int | None,
) -> None:
    ConversationMessageScope.from_message_fields(
        scope_kind=scope_kind,
        run_id=run_id,
        graph_id=graph_id,
        graph_version=graph_version,
        graph_ref=graph_ref,
        graph_checksum=graph_checksum,
        node_id=node_id,
        node_instance_id=node_instance_id,
        graph_checkpoint_ref=graph_checkpoint_ref,
        activity_id=activity_id,
        attempt=attempt,
    )


@dataclass(frozen=True)
class ConversationCompactionRecord:
    conversation_id: str
    summary: str
    original_message_count: int
    compacted_message_count: int
    retained_message_count: int
    marker_message_id: str
    compacted_until_message_id: str | None = None
    created_at: datetime = field(default_factory=_utc_now)
    redacted: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "summary": self.summary,
            "original_message_count": self.original_message_count,
            "compacted_message_count": self.compacted_message_count,
            "retained_message_count": self.retained_message_count,
            "marker_message_id": self.marker_message_id,
            "compacted_until_message_id": self.compacted_until_message_id,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "redacted": self.redacted,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ConversationCompactionRecord:
        return cls(
            conversation_id=str(payload["conversation_id"]),
            summary=str(payload.get("summary") or ""),
            original_message_count=int(payload.get("original_message_count") or 0),
            compacted_message_count=int(payload.get("compacted_message_count") or 0),
            retained_message_count=int(payload.get("retained_message_count") or 0),
            marker_message_id=str(payload["marker_message_id"]),
            compacted_until_message_id=_optional_str(payload.get("compacted_until_message_id")),
            created_at=_parse_datetime(str(payload["created_at"])),
            redacted=bool(payload.get("redacted", True)),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class ConversationCursor:
    conversation_id: str
    message_offset: int
    message_id: str | None = None
    run_id: str | None = None
    node_instance_id: str | None = None
    graph_checkpoint_ref: str | None = None
    updated_at: datetime = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = GRAPH_CONVERSATION_CURSOR_SCHEMA

    def __post_init__(self) -> None:
        if isinstance(self.message_offset, bool) or not isinstance(
            self.message_offset, int
        ):
            raise TypeError("message_offset must be an integer")
        if self.message_offset < 0:
            raise ValueError("message_offset must be non-negative")
        _validate_graph_outer_identity(
            run_id=self.run_id,
            node_instance_id=self.node_instance_id,
            graph_checkpoint_ref=self.graph_checkpoint_ref,
        )
        _validate_state_metadata(self.metadata)
        if self.schema_version != GRAPH_CONVERSATION_CURSOR_SCHEMA:
            raise ValueError("unsupported conversation cursor schema")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "conversation_id": self.conversation_id,
            "message_offset": self.message_offset,
            "message_id": self.message_id,
            "run_id": self.run_id,
            "node_instance_id": self.node_instance_id,
            "graph_checkpoint_ref": self.graph_checkpoint_ref,
            "updated_at": self.updated_at.isoformat().replace("+00:00", "Z"),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ConversationCursor:
        _require_exact_fields(
            payload,
            {
                "schema_version",
                "conversation_id",
                "message_offset",
                "message_id",
                "run_id",
                "node_instance_id",
                "graph_checkpoint_ref",
                "updated_at",
                "metadata",
            },
            "conversation cursor",
        )
        return cls(
            conversation_id=str(payload["conversation_id"]),
            message_offset=_required_integer(payload["message_offset"], "message_offset"),
            message_id=_optional_str(payload.get("message_id")),
            run_id=_optional_text(payload.get("run_id"), "run_id"),
            node_instance_id=_optional_text(
                payload.get("node_instance_id"), "node_instance_id"
            ),
            graph_checkpoint_ref=_optional_text(
                payload.get("graph_checkpoint_ref"), "graph_checkpoint_ref"
            ),
            updated_at=_parse_datetime(str(payload["updated_at"])),
            metadata=dict(payload.get("metadata") or {}),
            schema_version=str(payload["schema_version"]),
        )


@dataclass(frozen=True)
class AgentIterationCheckpoint:
    conversation_id: str
    agent_id: str
    iteration: int
    status: str
    stop_reason: str | None = None
    run_id: str | None = None
    node_instance_id: str | None = None
    graph_checkpoint_ref: str | None = None
    message_id: str | None = None
    trace_summary: dict[str, Any] = field(default_factory=dict)
    diagnostics_summary: dict[str, Any] = field(default_factory=dict)
    last_tool_observation: dict[str, Any] | None = None
    llm_call_artifact_ids: list[str] = field(default_factory=list)
    updated_at: datetime = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = GRAPH_AGENT_ITERATION_CHECKPOINT_SCHEMA

    def __post_init__(self) -> None:
        if isinstance(self.iteration, bool) or not isinstance(self.iteration, int):
            raise TypeError("iteration must be an integer")
        if self.iteration < 0:
            raise ValueError("iteration must be non-negative")
        _validate_graph_outer_identity(
            run_id=self.run_id,
            node_instance_id=self.node_instance_id,
            graph_checkpoint_ref=self.graph_checkpoint_ref,
        )
        _validate_state_metadata(self.metadata)
        if self.schema_version != GRAPH_AGENT_ITERATION_CHECKPOINT_SCHEMA:
            raise ValueError("unsupported agent iteration checkpoint schema")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "conversation_id": self.conversation_id,
            "agent_id": self.agent_id,
            "iteration": self.iteration,
            "status": self.status,
            "stop_reason": self.stop_reason,
            "run_id": self.run_id,
            "node_instance_id": self.node_instance_id,
            "graph_checkpoint_ref": self.graph_checkpoint_ref,
            "message_id": self.message_id,
            "trace_summary": dict(self.trace_summary),
            "diagnostics_summary": dict(self.diagnostics_summary),
            "last_tool_observation": (
                dict(self.last_tool_observation)
                if self.last_tool_observation is not None
                else None
            ),
            "llm_call_artifact_ids": list(self.llm_call_artifact_ids),
            "updated_at": self.updated_at.isoformat().replace("+00:00", "Z"),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AgentIterationCheckpoint:
        _require_exact_fields(
            payload,
            {
                "schema_version",
                "conversation_id",
                "agent_id",
                "iteration",
                "status",
                "stop_reason",
                "run_id",
                "node_instance_id",
                "graph_checkpoint_ref",
                "message_id",
                "trace_summary",
                "diagnostics_summary",
                "last_tool_observation",
                "llm_call_artifact_ids",
                "updated_at",
                "metadata",
            },
            "agent iteration checkpoint",
        )
        return cls(
            conversation_id=str(payload["conversation_id"]),
            agent_id=str(payload["agent_id"]),
            iteration=_required_integer(payload["iteration"], "iteration"),
            status=str(payload["status"]),
            stop_reason=_optional_str(payload.get("stop_reason")),
            run_id=_optional_text(payload.get("run_id"), "run_id"),
            node_instance_id=_optional_text(
                payload.get("node_instance_id"), "node_instance_id"
            ),
            graph_checkpoint_ref=_optional_text(
                payload.get("graph_checkpoint_ref"), "graph_checkpoint_ref"
            ),
            message_id=_optional_str(payload.get("message_id")),
            trace_summary=dict(payload.get("trace_summary") or {}),
            diagnostics_summary=dict(payload.get("diagnostics_summary") or {}),
            last_tool_observation=(
                dict(payload["last_tool_observation"])
                if isinstance(payload.get("last_tool_observation"), dict)
                else None
            ),
            llm_call_artifact_ids=[
                str(artifact_id)
                for artifact_id in payload.get("llm_call_artifact_ids") or []
            ],
            updated_at=_parse_datetime(str(payload["updated_at"])),
            metadata=dict(payload.get("metadata") or {}),
            schema_version=str(payload["schema_version"]),
        )


def _optional_text(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or len(value) > 2048
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(f"{field_name} must be a valid non-empty string")
    return value


def _required_integer(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    return value


def _validate_graph_outer_identity(
    *,
    run_id: str | None,
    node_instance_id: str | None,
    graph_checkpoint_ref: str | None,
) -> None:
    values = (run_id, node_instance_id, graph_checkpoint_ref)
    if all(value is None for value in values):
        return
    if any(value is None for value in values):
        raise ValueError(
            "Graph outer identity requires run_id, node_instance_id, and "
            "graph_checkpoint_ref together"
        )
    for field_name, value in (
        ("run_id", run_id),
        ("node_instance_id", node_instance_id),
        ("graph_checkpoint_ref", graph_checkpoint_ref),
    ):
        _optional_text(value, field_name)


def _require_exact_fields(
    payload: Any,
    expected: set[str],
    label: str,
) -> None:
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ValueError(f"{label} fields are invalid")


def _validate_state_metadata(metadata: Any) -> None:
    if not isinstance(metadata, dict):
        raise TypeError("conversation state metadata must be an object")
    forbidden = {
        "run_id",
        "node_instance_id",
        "graph_checkpoint_ref",
        "step_id",
        "workflow_checkpoint_id",
    }.intersection(metadata)
    if forbidden:
        raise ValueError(
            "conversation state metadata contains reserved identity fields: "
            + ", ".join(sorted(forbidden))
        )
