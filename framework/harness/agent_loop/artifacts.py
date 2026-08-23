from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from framework.agent.models import LLMCallArtifact
from framework.events.canonical import checksum_for
from framework.harness.artifacts import (
    ArtifactRef,
    ArtifactWriteRequest,
    RunBoundArtifactPort,
)
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.graph_runtime import HarnessGraphActivity
from framework.harness.control_plane.activity_execution import HarnessGraphActivityTaskContext
from framework.harness.workers.result import HarnessWorkerEvidence
from framework.shared.redaction import redact_sensitive_values


AGENT_LOOP_GRAPH_ARTIFACT_CONTEXT_SCHEMA = (
    "newsroom.agent-loop-graph-artifact-context/v1"
)
AGENT_LOOP_LLM_CALL_ARTIFACT_SCHEMA = "newsroom.agent-loop-llm-call-artifact/v1"
AGENT_LOOP_GRAPH_ARTIFACT_RECORD_SCHEMA = (
    "newsroom.agent-loop-graph-artifact-record/v1"
)
AGENT_LOOP_GRAPH_ARTIFACT_RECEIPT_SCHEMA = (
    "newsroom.agent-loop-graph-artifact-receipt/v1"
)
AGENT_LOOP_GRAPH_ARTIFACT_EVIDENCE_TYPE = "agent_loop_llm_call_artifacts"

_CHECKSUM_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
_SCHEMA_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@+-]*$")


@dataclass(frozen=True, slots=True)
class AgentLoopGraphArtifactContext:
    """Harness-owned Graph identity used to persist one AgentLoop call batch."""

    run_id: str
    graph_id: str
    graph_version: str
    graph_schema_version: str
    compiler_version: str
    normalized_graph_checksum: str
    node_id: str
    node_instance_id: str
    activity_id: str
    attempt: int
    graph_checkpoint_ref: str
    agent_id: str
    conversation_id: str | None = None
    tenant_scope_ref: str | None = None
    identity_scope_ref: str | None = None
    subject_scope_ref: str | None = None
    schema_version: str = AGENT_LOOP_GRAPH_ARTIFACT_CONTEXT_SCHEMA
    context_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        for field_name in (
            "run_id",
            "graph_id",
            "node_id",
            "node_instance_id",
            "activity_id",
            "graph_checkpoint_ref",
            "agent_id",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "graph_version",
            _version(self.graph_version, "graph_version"),
        )
        object.__setattr__(
            self,
            "compiler_version",
            _schema(self.compiler_version, "compiler_version"),
        )
        object.__setattr__(
            self,
            "graph_schema_version",
            _schema(self.graph_schema_version, "graph_schema_version"),
        )
        object.__setattr__(
            self,
            "normalized_graph_checksum",
            _checksum(
                self.normalized_graph_checksum,
                "normalized_graph_checksum",
            ),
        )
        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int):
            raise _context_error("attempt must be an integer")
        if self.attempt < 1:
            raise _context_error("attempt must be positive")
        object.__setattr__(
            self,
            "conversation_id",
            _optional_text(self.conversation_id, "conversation_id"),
        )
        for field_name in (
            "tenant_scope_ref",
            "identity_scope_ref",
            "subject_scope_ref",
        ):
            value = getattr(self, field_name)
            object.__setattr__(
                self,
                field_name,
                None if value is None else _checksum(value, field_name),
            )
        if self.schema_version != AGENT_LOOP_GRAPH_ARTIFACT_CONTEXT_SCHEMA:
            raise HarnessValidationError(
                "unsupported AgentLoop Graph artifact context schema",
                code="unsupported_agent_loop_graph_artifact_schema",
            )
        object.__setattr__(
            self,
            "context_checksum",
            checksum_for(self.checksum_projection()),
        )

    @classmethod
    def from_activity(
        cls,
        activity: HarnessGraphActivity,
        *,
        graph_version: str,
        graph_checkpoint_ref: str,
        agent_id: str,
        conversation_id: str | None = None,
    ) -> AgentLoopGraphArtifactContext:
        if not isinstance(activity, HarnessGraphActivity):
            raise TypeError("activity must be HarnessGraphActivity")
        return cls(
            run_id=activity.run_id,
            graph_id=activity.graph_ref.graph_id,
            graph_version=graph_version,
            graph_schema_version=activity.graph_ref.schema_version,
            compiler_version=activity.graph_ref.compiler_version,
            normalized_graph_checksum=activity.graph_ref.checksum,
            node_id=activity.node_id,
            node_instance_id=activity.node_instance_id,
            activity_id=activity.activity_id,
            attempt=activity.attempt,
            graph_checkpoint_ref=graph_checkpoint_ref,
            agent_id=agent_id,
            conversation_id=conversation_id,
            tenant_scope_ref=activity.tenant_scope_ref,
            identity_scope_ref=activity.identity_scope_ref,
            subject_scope_ref=activity.subject_scope_ref,
        )

    @classmethod
    def from_task_context(
        cls,
        task_context: HarnessGraphActivityTaskContext,
        *,
        graph_version: str,
        agent_id: str,
        conversation_id: str | None = None,
    ) -> AgentLoopGraphArtifactContext:
        if not isinstance(task_context, HarnessGraphActivityTaskContext):
            raise TypeError(
                "task_context must be HarnessGraphActivityTaskContext"
            )
        return cls.from_activity(
            task_context.activity,
            graph_version=graph_version,
            graph_checkpoint_ref=task_context.graph_checkpoint_ref,
            agent_id=agent_id,
            conversation_id=conversation_id,
        )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "graph_id": self.graph_id,
            "graph_version": self.graph_version,
            "graph_schema_version": self.graph_schema_version,
            "compiler_version": self.compiler_version,
            "normalized_graph_checksum": self.normalized_graph_checksum,
            "node_id": self.node_id,
            "node_instance_id": self.node_instance_id,
            "activity_id": self.activity_id,
            "attempt": self.attempt,
            "graph_checkpoint_ref": self.graph_checkpoint_ref,
            "agent_id": self.agent_id,
            "conversation_id": self.conversation_id,
            "tenant_scope_ref": self.tenant_scope_ref,
            "identity_scope_ref": self.identity_scope_ref,
            "subject_scope_ref": self.subject_scope_ref,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.checksum_projection(),
            "context_checksum": self.context_checksum,
        }

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> AgentLoopGraphArtifactContext:
        expected = {
            "schema_version",
            "run_id",
            "graph_id",
            "graph_version",
            "graph_schema_version",
            "compiler_version",
            "normalized_graph_checksum",
            "node_id",
            "node_instance_id",
            "activity_id",
            "attempt",
            "graph_checkpoint_ref",
            "agent_id",
            "conversation_id",
            "tenant_scope_ref",
            "identity_scope_ref",
            "subject_scope_ref",
            "context_checksum",
        }
        payload = _exact_mapping(value, expected, "artifact context")
        supplied_checksum = payload.pop("context_checksum")
        context = cls(**payload)
        if supplied_checksum != context.context_checksum:
            raise _context_error("context checksum does not match")
        return context


@dataclass(frozen=True, slots=True)
class AgentLoopGraphArtifactRecord:
    source_artifact_id: str
    iteration: int
    artifact_ref: ArtifactRef
    call_checksum: str
    schema_version: str = AGENT_LOOP_GRAPH_ARTIFACT_RECORD_SCHEMA
    record_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_artifact_id",
            _required_text(self.source_artifact_id, "source_artifact_id"),
        )
        if isinstance(self.iteration, bool) or not isinstance(self.iteration, int):
            raise _batch_error("artifact iteration must be an integer")
        if self.iteration < 1:
            raise _batch_error("artifact iteration must be positive")
        if not isinstance(self.artifact_ref, ArtifactRef):
            raise TypeError("artifact_ref must be ArtifactRef")
        object.__setattr__(
            self,
            "call_checksum",
            _checksum(self.call_checksum, "call_checksum"),
        )
        if self.schema_version != AGENT_LOOP_GRAPH_ARTIFACT_RECORD_SCHEMA:
            raise HarnessValidationError(
                "unsupported AgentLoop Graph artifact record schema",
                code="unsupported_agent_loop_graph_artifact_schema",
            )
        object.__setattr__(
            self,
            "record_checksum",
            checksum_for(self.checksum_projection()),
        )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_artifact_id": self.source_artifact_id,
            "iteration": self.iteration,
            "artifact_ref": self.artifact_ref.to_dict(),
            "call_checksum": self.call_checksum,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.checksum_projection(),
            "record_checksum": self.record_checksum,
        }

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> AgentLoopGraphArtifactRecord:
        expected = {
            "schema_version",
            "source_artifact_id",
            "iteration",
            "artifact_ref",
            "call_checksum",
            "record_checksum",
        }
        payload = _exact_mapping(value, expected, "artifact record")
        supplied_checksum = payload.pop("record_checksum")
        artifact_ref = payload.get("artifact_ref")
        if not isinstance(artifact_ref, Mapping):
            raise _batch_error("artifact record ref must be an object")
        payload["artifact_ref"] = _artifact_ref_from_dict(artifact_ref)
        record = cls(**payload)
        if supplied_checksum != record.record_checksum:
            raise _batch_error("artifact record checksum does not match")
        return record


@dataclass(frozen=True, slots=True)
class AgentLoopGraphArtifactReceipt:
    context: AgentLoopGraphArtifactContext
    records: tuple[AgentLoopGraphArtifactRecord, ...]
    schema_version: str = AGENT_LOOP_GRAPH_ARTIFACT_RECEIPT_SCHEMA
    receipt_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.context, AgentLoopGraphArtifactContext):
            raise TypeError("context must be AgentLoopGraphArtifactContext")
        records = tuple(self.records)
        if not all(isinstance(item, AgentLoopGraphArtifactRecord) for item in records):
            raise TypeError("records must contain AgentLoopGraphArtifactRecord values")
        identities = [
            (item.source_artifact_id, item.iteration, item.artifact_ref.ref)
            for item in records
        ]
        if len(identities) != len(set(identities)):
            raise _batch_error("artifact receipt contains duplicate records")
        if records != tuple(
            sorted(records, key=lambda item: (item.iteration, item.source_artifact_id))
        ):
            raise _batch_error("artifact receipt records must be canonical")
        object.__setattr__(self, "records", records)
        if self.schema_version != AGENT_LOOP_GRAPH_ARTIFACT_RECEIPT_SCHEMA:
            raise HarnessValidationError(
                "unsupported AgentLoop Graph artifact receipt schema",
                code="unsupported_agent_loop_graph_artifact_schema",
            )
        object.__setattr__(
            self,
            "receipt_checksum",
            checksum_for(self.checksum_projection()),
        )

    @property
    def artifact_refs(self) -> tuple[str, ...]:
        return tuple(item.artifact_ref.ref for item in self.records)

    def worker_evidence(self) -> HarnessWorkerEvidence:
        return HarnessWorkerEvidence(
            evidence_type=AGENT_LOOP_GRAPH_ARTIFACT_EVIDENCE_TYPE,
            payload=self.to_dict(),
        )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "context": self.context.to_dict(),
            "records": [item.to_dict() for item in self.records],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.checksum_projection(),
            "receipt_checksum": self.receipt_checksum,
        }

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> AgentLoopGraphArtifactReceipt:
        expected = {
            "schema_version",
            "context",
            "records",
            "receipt_checksum",
        }
        payload = _exact_mapping(value, expected, "artifact receipt")
        supplied_checksum = payload.pop("receipt_checksum")
        context = payload.get("context")
        records = payload.get("records")
        if not isinstance(context, Mapping):
            raise _batch_error("artifact receipt context must be an object")
        if isinstance(records, str | bytes) or not isinstance(records, Sequence):
            raise _batch_error("artifact receipt records must be an array")
        payload["context"] = AgentLoopGraphArtifactContext.from_dict(context)
        payload["records"] = tuple(
            AgentLoopGraphArtifactRecord.from_dict(item)
            for item in records
        )
        receipt = cls(**payload)
        if supplied_checksum != receipt.receipt_checksum:
            raise _batch_error("artifact receipt checksum does not match")
        return receipt


@dataclass(frozen=True, slots=True)
class AgentLoopGraphArtifactRecorder:
    """Persist redacted AgentLoop LLM calls without publication authority."""

    artifact_port: RunBoundArtifactPort

    def __post_init__(self) -> None:
        if not isinstance(self.artifact_port, RunBoundArtifactPort):
            raise TypeError("artifact_port must implement RunBoundArtifactPort")

    def record(
        self,
        *,
        context: AgentLoopGraphArtifactContext,
        artifacts: Sequence[LLMCallArtifact],
    ) -> AgentLoopGraphArtifactReceipt:
        if not isinstance(context, AgentLoopGraphArtifactContext):
            raise TypeError("context must be AgentLoopGraphArtifactContext")
        if isinstance(artifacts, str | bytes) or not isinstance(artifacts, Sequence):
            raise TypeError("artifacts must be a sequence of LLMCallArtifact values")
        calls = tuple(artifacts)
        if not all(isinstance(item, LLMCallArtifact) for item in calls):
            raise TypeError("artifacts must contain LLMCallArtifact values")
        _validate_calls(calls, context=context)

        records: list[AgentLoopGraphArtifactRecord] = []
        with self.artifact_port.bind_run(context.run_id):
            for call in sorted(
                calls,
                key=lambda item: (item.iteration, item.artifact_id),
            ):
                request, call_checksum = _write_request(context, call)
                artifact_ref = self.artifact_port.write_artifact(request)
                _validate_written_ref(artifact_ref, request)
                persisted = self.artifact_port.read_artifact(artifact_ref.ref)
                if persisted != request.to_dict():
                    raise HarnessValidationError(
                        "AgentLoop artifact read-back does not match its write request",
                        code="agent_loop_graph_artifact_integrity_mismatch",
                        details={"artifact_ref": artifact_ref.ref},
                    )
                records.append(
                    AgentLoopGraphArtifactRecord(
                        source_artifact_id=call.artifact_id,
                        iteration=call.iteration,
                        artifact_ref=artifact_ref,
                        call_checksum=call_checksum,
                    )
                )
        return AgentLoopGraphArtifactReceipt(
            context=context,
            records=tuple(records),
        )


def _write_request(
    context: AgentLoopGraphArtifactContext,
    call: LLMCallArtifact,
) -> tuple[ArtifactWriteRequest, str]:
    projection = {
        "schema_version": AGENT_LOOP_LLM_CALL_ARTIFACT_SCHEMA,
        "context": context.to_dict(),
        "source_artifact_id": call.artifact_id,
        "iteration": call.iteration,
        "request": redact_sensitive_values(dict(call.request)),
        "response": redact_sensitive_values(dict(call.response)),
        "metadata": redact_sensitive_values(dict(call.metadata)),
    }
    call_checksum = checksum_for(projection)
    payload = {**projection, "call_checksum": call_checksum}
    artifact_type = _artifact_type(call_checksum)
    metadata = {
        "artifact_schema_version": AGENT_LOOP_LLM_CALL_ARTIFACT_SCHEMA,
        "artifact_role": "agent_loop_llm_call",
        "run_id": context.run_id,
        "graph_id": context.graph_id,
        "graph_version": context.graph_version,
        "graph_schema_version": context.graph_schema_version,
        "compiler_version": context.compiler_version,
        "normalized_graph_checksum": context.normalized_graph_checksum,
        "node_id": context.node_id,
        "node_instance_id": context.node_instance_id,
        "activity_id": context.activity_id,
        "attempt": context.attempt,
        "attempt_id": context.activity_id,
        "graph_checkpoint_ref": context.graph_checkpoint_ref,
        "agent_id": context.agent_id,
        "conversation_id": context.conversation_id,
        "context_checksum": context.context_checksum,
        "source_artifact_id": call.artifact_id,
        "iteration": call.iteration,
        "call_checksum": call_checksum,
        "graph_result_ref_only": True,
        "identity_checksum": call_checksum,
        "required_for_replay": True,
        "required_for_publication": False,
        "redacted": True,
    }
    return (
        ArtifactWriteRequest(
            artifact_type=artifact_type,
            payload=payload,
            media_type="application/json",
            metadata=metadata,
        ),
        call_checksum,
    )


def _validate_calls(
    calls: tuple[LLMCallArtifact, ...],
    *,
    context: AgentLoopGraphArtifactContext,
) -> None:
    identities: list[tuple[str, int]] = []
    for call in calls:
        artifact_id = _required_text(call.artifact_id, "artifact_id")
        if isinstance(call.iteration, bool) or not isinstance(call.iteration, int):
            raise _batch_error("LLM call iteration must be an integer")
        if call.iteration < 1:
            raise _batch_error("LLM call iteration must be positive")
        if not isinstance(call.request, Mapping) or not isinstance(
            call.response,
            Mapping,
        ):
            raise _batch_error("LLM call request and response must be objects")
        if not isinstance(call.metadata, Mapping):
            raise _batch_error("LLM call metadata must be an object")
        metadata_agent_id = call.metadata.get("agent_id")
        if metadata_agent_id != context.agent_id:
            raise HarnessValidationError(
                "AgentLoop artifact belongs to another agent",
                code="agent_loop_graph_artifact_context_mismatch",
                details={
                    "expected_agent_id": context.agent_id,
                    "actual_agent_id": metadata_agent_id,
                },
            )
        identities.append((artifact_id, call.iteration))
    if len(identities) != len(set(identities)):
        raise _batch_error("LLM call artifacts must have unique identities")
    artifact_ids = [artifact_id for artifact_id, _ in identities]
    iterations = [iteration for _, iteration in identities]
    if len(artifact_ids) != len(set(artifact_ids)) or len(iterations) != len(
        set(iterations)
    ):
        raise _batch_error("LLM call artifact ids and iterations must be unique")


def _validate_written_ref(
    artifact_ref: ArtifactRef,
    request: ArtifactWriteRequest,
) -> None:
    if not isinstance(artifact_ref, ArtifactRef):
        raise HarnessValidationError(
            "artifact owner returned an invalid AgentLoop artifact ref",
            code="agent_loop_graph_artifact_integrity_mismatch",
        )
    mismatches = [
        field_name
        for field_name, expected, actual in (
            ("artifact_type", request.artifact_type, artifact_ref.artifact_type),
            ("media_type", request.media_type, artifact_ref.media_type),
            ("metadata", request.metadata, artifact_ref.metadata),
        )
        if expected != actual
    ]
    if not _CHECKSUM_PATTERN.fullmatch(artifact_ref.checksum):
        mismatches.append("checksum")
    if mismatches:
        raise HarnessValidationError(
            "artifact owner returned a conflicting AgentLoop artifact ref",
            code="agent_loop_graph_artifact_integrity_mismatch",
            details={"mismatches": sorted(mismatches)},
        )


def _artifact_type(
    call_checksum: str,
) -> str:
    digest = _checksum(call_checksum, "call_checksum").removeprefix("sha256:")
    return f"graph-result-{digest}"


def _artifact_ref_from_dict(value: Mapping[str, Any]) -> ArtifactRef:
    expected = {"ref", "artifact_type", "checksum", "media_type", "metadata"}
    payload = _exact_mapping(value, expected, "artifact ref")
    metadata = payload.get("metadata")
    if not isinstance(metadata, Mapping):
        raise _batch_error("artifact ref metadata must be an object")
    payload["metadata"] = dict(metadata)
    return ArtifactRef(**payload)


def _exact_mapping(
    value: Mapping[str, Any],
    expected: set[str],
    field_name: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise HarnessValidationError(
            f"AgentLoop Graph {field_name} fields are invalid",
            code="agent_loop_graph_artifact_contract_invalid",
            details={
                "expected": sorted(expected),
                "actual": sorted(str(key) for key in value)
                if isinstance(value, Mapping)
                else [],
            },
        )
    return dict(value)


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise _context_error(f"{field_name} must be a non-blank trimmed string")
    return value


def _optional_text(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field_name)


def _version(value: Any, field_name: str) -> str:
    normalized = _required_text(value, field_name)
    if not _VERSION_PATTERN.fullmatch(normalized):
        raise _context_error(f"{field_name} is invalid")
    return normalized


def _schema(value: Any, field_name: str) -> str:
    normalized = _required_text(value, field_name)
    if not _SCHEMA_PATTERN.fullmatch(normalized):
        raise _context_error(f"{field_name} is invalid")
    return normalized


def _checksum(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _CHECKSUM_PATTERN.fullmatch(value):
        raise _context_error(f"{field_name} must be a sha256 reference")
    return value


def _context_error(message: str) -> HarnessValidationError:
    return HarnessValidationError(
        message,
        code="agent_loop_graph_artifact_context_invalid",
    )


def _batch_error(message: str) -> HarnessValidationError:
    return HarnessValidationError(
        message,
        code="agent_loop_graph_artifact_batch_invalid",
    )


__all__ = [
    "AGENT_LOOP_GRAPH_ARTIFACT_CONTEXT_SCHEMA",
    "AGENT_LOOP_GRAPH_ARTIFACT_EVIDENCE_TYPE",
    "AGENT_LOOP_GRAPH_ARTIFACT_RECEIPT_SCHEMA",
    "AGENT_LOOP_GRAPH_ARTIFACT_RECORD_SCHEMA",
    "AGENT_LOOP_LLM_CALL_ARTIFACT_SCHEMA",
    "AgentLoopGraphArtifactContext",
    "AgentLoopGraphArtifactReceipt",
    "AgentLoopGraphArtifactRecord",
    "AgentLoopGraphArtifactRecorder",
]
