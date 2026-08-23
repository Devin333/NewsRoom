from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.subagents.transcript import (
    SubAgentAttemptIdentity,
    SubAgentTranscriptReceipt,
)


SUBAGENT_TRANSCRIPT_COMMIT_SUCCEEDED = "subagent_transcript_commit_succeeded"
SUBAGENT_TRANSCRIPT_COMMIT_FAILED = "subagent_transcript_commit_failed"
SUBAGENT_TRANSCRIPT_VERIFY_FAILED = "subagent_transcript_verify_failed"
SUBAGENT_TRANSCRIPT_CONFLICT = "subagent_transcript_conflict"
SUBAGENT_TRANSCRIPT_CORRUPT = "subagent_transcript_corrupt"
SUBAGENT_TRANSCRIPT_BYTES = "subagent_transcript_bytes"
SUBAGENT_TRANSCRIPT_COMMIT_LATENCY_MS = "subagent_transcript_commit_latency_ms"
SUBAGENT_TRANSCRIPT_RECOVERY_REUSED_TOTAL = (
    "subagent_transcript_recovery_reused_total"
)
SUBAGENT_TRANSCRIPT_OBSERVATION_NAMES = frozenset(
    {
        SUBAGENT_TRANSCRIPT_COMMIT_SUCCEEDED,
        SUBAGENT_TRANSCRIPT_COMMIT_FAILED,
        SUBAGENT_TRANSCRIPT_VERIFY_FAILED,
        SUBAGENT_TRANSCRIPT_CONFLICT,
        SUBAGENT_TRANSCRIPT_CORRUPT,
        SUBAGENT_TRANSCRIPT_BYTES,
        SUBAGENT_TRANSCRIPT_COMMIT_LATENCY_MS,
        SUBAGENT_TRANSCRIPT_RECOVERY_REUSED_TOTAL,
    }
)

_CHECKSUM_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_REASON_CODE_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]*\Z")
_LOGGER = logging.getLogger("newsroom.harness.subagent_transcript")


@dataclass(frozen=True, slots=True)
class SubAgentTranscriptObservation:
    """Bounded operator evidence; transcript bodies are intentionally absent."""

    name: str
    transcript_id: str | None = None
    invocation_id: str | None = None
    parent_run_id: str | None = None
    child_run_id: str | None = None
    stage_id: str | None = None
    task_id: str | None = None
    task_instance_id: str | None = None
    attempt: int | None = None
    subagent_id: str | None = None
    transcript_ref: str | None = None
    transcript_checksum: str | None = None
    output_ref: str | None = None
    output_checksum: str | None = None
    reason_code: str | None = None
    value: float | None = None

    def __post_init__(self) -> None:
        if self.name not in SUBAGENT_TRANSCRIPT_OBSERVATION_NAMES:
            raise HarnessValidationError(
                "subagent transcript observation name is invalid",
                code="subagent_transcript_observation_invalid",
            )
        for field_name in (
            "transcript_id",
            "invocation_id",
            "parent_run_id",
            "child_run_id",
            "stage_id",
            "task_id",
            "task_instance_id",
            "subagent_id",
            "transcript_ref",
            "output_ref",
        ):
            value = getattr(self, field_name)
            if value is not None and (
                not isinstance(value, str)
                or not value
                or value != value.strip()
                or len(value) > 2048
            ):
                raise HarnessValidationError(
                    "subagent transcript observation identity is invalid",
                    code="subagent_transcript_observation_invalid",
                    details={"field": field_name},
                )
        for field_name in ("transcript_checksum", "output_checksum"):
            value = getattr(self, field_name)
            if value is not None and (
                not isinstance(value, str)
                or _CHECKSUM_PATTERN.fullmatch(value) is None
            ):
                raise HarnessValidationError(
                    "subagent transcript observation checksum is invalid",
                    code="subagent_transcript_observation_invalid",
                    details={"field": field_name},
                )
        if self.attempt is not None and (
            isinstance(self.attempt, bool)
            or not isinstance(self.attempt, int)
            or self.attempt <= 0
        ):
            raise HarnessValidationError(
                "subagent transcript observation attempt is invalid",
                code="subagent_transcript_observation_invalid",
            )
        if self.reason_code is not None and (
            not isinstance(self.reason_code, str)
            or _REASON_CODE_PATTERN.fullmatch(self.reason_code) is None
        ):
            raise HarnessValidationError(
                "subagent transcript observation reason code is invalid",
                code="subagent_transcript_observation_invalid",
            )
        if self.value is not None and (
            isinstance(self.value, bool)
            or not isinstance(self.value, int | float)
            or not math.isfinite(float(self.value))
            or self.value < 0
        ):
            raise HarnessValidationError(
                "subagent transcript observation value is invalid",
                code="subagent_transcript_observation_invalid",
            )
        object.__setattr__(
            self,
            "value",
            None if self.value is None else float(self.value),
        )

    @classmethod
    def from_identity(
        cls,
        name: str,
        identity: SubAgentAttemptIdentity,
        *,
        receipt: SubAgentTranscriptReceipt | None = None,
        reason_code: str | None = None,
        value: float | None = None,
    ) -> "SubAgentTranscriptObservation":
        if not isinstance(identity, SubAgentAttemptIdentity):
            raise TypeError("identity must be SubAgentAttemptIdentity")
        if receipt is not None and not isinstance(receipt, SubAgentTranscriptReceipt):
            raise TypeError("receipt must be SubAgentTranscriptReceipt")
        return cls(
            name=name,
            transcript_id=identity.transcript_id,
            invocation_id=identity.invocation_id,
            parent_run_id=identity.parent_run_id,
            child_run_id=identity.child_run_id,
            stage_id=identity.stage_id,
            task_id=identity.task_id,
            task_instance_id=identity.task_instance_id,
            attempt=identity.attempt,
            subagent_id=identity.subagent_id,
            transcript_ref=receipt.transcript_ref if receipt else None,
            transcript_checksum=receipt.transcript_checksum if receipt else None,
            output_ref=receipt.output_ref if receipt else None,
            output_checksum=receipt.output_checksum if receipt else None,
            reason_code=reason_code,
            value=value,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "transcript_id": self.transcript_id,
            "invocation_id": self.invocation_id,
            "parent_run_id": self.parent_run_id,
            "child_run_id": self.child_run_id,
            "stage_id": self.stage_id,
            "task_id": self.task_id,
            "task_instance_id": self.task_instance_id,
            "attempt": self.attempt,
            "subagent_id": self.subagent_id,
            "transcript_ref": self.transcript_ref,
            "transcript_checksum": self.transcript_checksum,
            "output_ref": self.output_ref,
            "output_checksum": self.output_checksum,
            "reason_code": self.reason_code,
            "value": self.value,
        }


@runtime_checkable
class SubAgentTranscriptObservationSink(Protocol):
    def record(self, observation: SubAgentTranscriptObservation) -> None: ...


class LoggingSubAgentTranscriptObservationSink:
    def record(self, observation: SubAgentTranscriptObservation) -> None:
        if not isinstance(observation, SubAgentTranscriptObservation):
            raise TypeError("observation must be SubAgentTranscriptObservation")
        _LOGGER.info(
            observation.name,
            extra={"subagent_transcript_observation": observation.to_dict()},
        )


DEFAULT_SUBAGENT_TRANSCRIPT_OBSERVATION_SINK = (
    LoggingSubAgentTranscriptObservationSink()
)


def record_subagent_transcript_observation(
    sink: SubAgentTranscriptObservationSink | None,
    observation: SubAgentTranscriptObservation,
) -> None:
    """Best-effort telemetry boundary; observability never controls execution."""

    if sink is None:
        return
    try:
        sink.record(observation)
    except Exception:
        _LOGGER.exception(
            "subagent_transcript_observation_sink_failed",
            extra={"subagent_transcript_observation_name": observation.name},
        )


__all__ = [
    "DEFAULT_SUBAGENT_TRANSCRIPT_OBSERVATION_SINK",
    "LoggingSubAgentTranscriptObservationSink",
    "SUBAGENT_TRANSCRIPT_BYTES",
    "SUBAGENT_TRANSCRIPT_COMMIT_FAILED",
    "SUBAGENT_TRANSCRIPT_COMMIT_LATENCY_MS",
    "SUBAGENT_TRANSCRIPT_COMMIT_SUCCEEDED",
    "SUBAGENT_TRANSCRIPT_CONFLICT",
    "SUBAGENT_TRANSCRIPT_CORRUPT",
    "SUBAGENT_TRANSCRIPT_OBSERVATION_NAMES",
    "SUBAGENT_TRANSCRIPT_RECOVERY_REUSED_TOTAL",
    "SUBAGENT_TRANSCRIPT_VERIFY_FAILED",
    "SubAgentTranscriptObservation",
    "SubAgentTranscriptObservationSink",
    "record_subagent_transcript_observation",
]
