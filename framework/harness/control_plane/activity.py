from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from framework.events.canonical import (
    PayloadReference,
    checksum_for,
    normalize_canonical_json,
    thaw_canonical_json,
)
from framework.events.errors import (
    EventIncompleteHistoryError,
    EventStoreCorruptionError,
)
from framework.events.schema.security import (
    SecurePayloadStorePort,
    SecurePayloadValidation,
    SecurityClassification,
)
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.workers.result import HarnessWorkerResult
from framework.shared.json import stable_json_dumps, to_jsonable
from framework.shared.time import ensure_utc, format_datetime, parse_datetime


HARNESS_ACTIVITY_CONTRACT = "newsroom.harness-worker-activity/v1"
HARNESS_ACTIVITY_RESULT_SCHEMA = "newsroom.harness-activity-result/v1"
HARNESS_ACTIVITY_EXTENSION = "harness_activity"


@dataclass(frozen=True, slots=True)
class HarnessActivity:
    activity_id: str
    run_id: str
    step_id: str
    attempt: int
    activity_type: str
    idempotency_key: str
    input_checksum: str
    identity_scope_ref: str | None = None
    contract_version: str = HARNESS_ACTIVITY_CONTRACT
    worker_version: str = "1"

    def __post_init__(self) -> None:
        for field_name in (
            "activity_id",
            "run_id",
            "step_id",
            "activity_type",
            "idempotency_key",
            "input_checksum",
            "contract_version",
            "worker_version",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise HarnessValidationError(f"{field_name} is required")
            object.__setattr__(self, field_name, value)
        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int):
            raise HarnessValidationError("activity attempt must be an integer")
        if self.attempt < 1:
            raise HarnessValidationError("activity attempt must be greater than zero")
        if not self.input_checksum.startswith("sha256:"):
            raise HarnessValidationError("activity input_checksum must be a sha256 reference")
        if self.identity_scope_ref is not None:
            identity_scope_ref = str(self.identity_scope_ref).strip()
            if not _is_checksum(identity_scope_ref):
                raise HarnessValidationError(
                    "activity identity_scope_ref must be a sha256 reference"
                )
            object.__setattr__(self, "identity_scope_ref", identity_scope_ref)

    @classmethod
    def for_worker_call(
        cls,
        *,
        run_id: str,
        step_id: str,
        attempt: int,
        activity_type: str,
        inputs: Mapping[str, Any],
        identity_scope_ref: str | None = None,
        contract_version: str = HARNESS_ACTIVITY_CONTRACT,
        worker_version: str = "1",
    ) -> HarnessActivity:
        identity = {
            "run_id": str(run_id),
            "step_id": str(step_id),
            "attempt": attempt,
            "activity_type": str(activity_type),
            "contract_version": str(contract_version),
        }
        if identity_scope_ref is not None:
            identity["identity_scope_ref"] = str(identity_scope_ref)
        digest = hashlib.sha256(
            stable_json_dumps(identity).encode("utf-8")
        ).hexdigest()
        identity_prefix = (
            "harness-activity-v2" if identity_scope_ref is not None else "harness-activity"
        )
        return cls(
            activity_id=f"{identity_prefix}:{digest}",
            run_id=run_id,
            step_id=step_id,
            attempt=attempt,
            activity_type=activity_type,
            idempotency_key=f"{identity_prefix}:{digest}",
            input_checksum=checksum_for(to_jsonable(inputs)),
            identity_scope_ref=identity_scope_ref,
            contract_version=contract_version,
            worker_version=worker_version,
        )

    @property
    def result_event_id(self) -> str:
        digest = hashlib.sha256(
            f"{self.activity_id}|result|{HARNESS_ACTIVITY_RESULT_SCHEMA}".encode("utf-8")
        ).hexdigest()
        prefix = "harness-event-v2" if self.identity_scope_ref is not None else "harness-event"
        return f"{prefix}:{digest}"

    def to_dict(self) -> dict[str, Any]:
        value = {
            "activity_id": self.activity_id,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "attempt": self.attempt,
            "activity_type": self.activity_type,
            "contract_version": self.contract_version,
            "idempotency_key": self.idempotency_key,
            "input_checksum": self.input_checksum,
            "worker_version": self.worker_version,
        }
        if self.identity_scope_ref is not None:
            value["identity_scope_ref"] = self.identity_scope_ref
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HarnessActivity:
        return cls(
            activity_id=value.get("activity_id"),
            run_id=value.get("run_id"),
            step_id=value.get("step_id"),
            attempt=value.get("attempt"),
            activity_type=value.get("activity_type"),
            contract_version=value.get("contract_version"),
            idempotency_key=value.get("idempotency_key"),
            input_checksum=value.get("input_checksum"),
            identity_scope_ref=value.get("identity_scope_ref"),
            worker_version=value.get("worker_version"),
        )


@dataclass(frozen=True, slots=True)
class HarnessActivityResultRecord:
    activity: HarnessActivity
    result: HarnessWorkerResult
    completed_at: datetime
    accepted_at: datetime | None = None
    started_at: datetime | None = None
    schema: str = HARNESS_ACTIVITY_RESULT_SCHEMA
    _snapshot: Mapping[str, Any] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.activity, HarnessActivity):
            raise TypeError("activity must be HarnessActivity")
        if not isinstance(self.result, HarnessWorkerResult):
            raise TypeError("result must be HarnessWorkerResult")
        if self.schema != HARNESS_ACTIVITY_RESULT_SCHEMA:
            raise HarnessValidationError("unsupported Harness activity result schema")
        explicit_lifecycle = (
            self.accepted_at is not None or self.started_at is not None
        )
        if (self.accepted_at is None) != (self.started_at is None):
            raise HarnessValidationError(
                "accepted_at and started_at must be supplied together"
            )
        if not isinstance(self.completed_at, datetime):
            raise HarnessValidationError("completed_at must be a datetime")
        completed_at = ensure_utc(self.completed_at)
        accepted_at = (
            completed_at
            if self.accepted_at is None
            else ensure_utc(self.accepted_at)
        )
        started_at = (
            completed_at
            if self.started_at is None
            else ensure_utc(self.started_at)
        )
        if accepted_at > started_at or started_at > completed_at:
            raise HarnessValidationError(
                "activity lifecycle times must satisfy accepted_at <= started_at <= completed_at"
            )
        object.__setattr__(self, "accepted_at", accepted_at)
        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(self, "completed_at", completed_at)
        snapshot_value = {
            "schema": self.schema,
            "activity": self.activity.to_dict(),
            "result": self.result.to_dict(),
            "completed_at": format_datetime(completed_at),
        }
        if explicit_lifecycle:
            snapshot_value.update(
                {
                    "accepted_at": format_datetime(accepted_at),
                    "started_at": format_datetime(started_at),
                }
            )
        snapshot = normalize_canonical_json(
            snapshot_value,
            path="$.harness_activity_result",
        )
        if not isinstance(snapshot, Mapping):
            raise HarnessValidationError("Harness activity result must be an object")
        object.__setattr__(self, "_snapshot", snapshot)

    @property
    def content_checksum(self) -> str:
        return checksum_for(self._snapshot)

    def to_dict(self) -> dict[str, Any]:
        value = thaw_canonical_json(self._snapshot)
        if not isinstance(value, dict):  # pragma: no cover - constructor invariant
            raise EventStoreCorruptionError("Harness activity result snapshot is invalid")
        return value

    def to_worker_result(self) -> HarnessWorkerResult:
        value = self.to_dict().get("result")
        if not isinstance(value, Mapping):  # pragma: no cover - constructor invariant
            raise EventStoreCorruptionError("Harness activity result payload is invalid")
        return _worker_result_from_dict(value)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HarnessActivityResultRecord:
        try:
            normalized = normalize_canonical_json(
                to_jsonable(value),
                path="$.harness_activity_result",
            )
            if not isinstance(normalized, Mapping):
                raise EventStoreCorruptionError(
                    "Harness activity result must be an object"
                )
            raw = thaw_canonical_json(normalized)
            activity_value = raw.get("activity")
            result_value = raw.get("result")
            if not isinstance(activity_value, Mapping) or not isinstance(
                result_value, Mapping
            ):
                raise EventStoreCorruptionError(
                    "Harness activity result is missing activity or result"
                )
            completed_at = parse_datetime(raw.get("completed_at"))
            if completed_at is None:
                raise EventStoreCorruptionError(
                    "Harness activity result completed_at is invalid"
                )
            return cls(
                schema=str(raw.get("schema") or ""),
                activity=HarnessActivity.from_dict(activity_value),
                result=_worker_result_from_dict(result_value),
                completed_at=completed_at,
                accepted_at=parse_datetime(raw.get("accepted_at")),
                started_at=parse_datetime(raw.get("started_at")),
            )
        except EventStoreCorruptionError:
            raise
        except (HarnessValidationError, TypeError, ValueError) as exc:
            raise EventStoreCorruptionError(
                "Harness activity result contract is invalid"
            ) from exc


@runtime_checkable
class SecureHarnessActivityStorePort(SecurePayloadStorePort, Protocol):
    """Authorized encrypted storage for complete worker activity results."""

    def put_result(
        self,
        record: HarnessActivityResultRecord,
        *,
        tenant_id: str,
        classification: SecurityClassification,
    ) -> PayloadReference:
        """Put once by activity identity and return an integrity-bound reference."""
        ...

    def resolve_result(
        self,
        reference: PayloadReference,
        *,
        tenant_id: str,
        classification: SecurityClassification,
    ) -> HarnessActivityResultRecord:
        """Authorize, decrypt, and verify one complete activity result."""
        ...

    def validate_reference(
        self,
        reference: Mapping[str, Any],
        *,
        tenant_id: str,
        classification: SecurityClassification,
    ) -> SecurePayloadValidation:
        ...


def resolve_activity_result(
    store: SecureHarnessActivityStorePort,
    reference: PayloadReference,
    *,
    expected_activity: HarnessActivity,
    tenant_id: str,
    classification: SecurityClassification,
) -> HarnessActivityResultRecord:
    if store is None:
        raise EventIncompleteHistoryError(
            "secure Harness activity result store is unavailable"
        )
    try:
        validation = store.validate_reference(
            reference.to_dict(),
            tenant_id=tenant_id,
            classification=classification,
        )
    except EventStoreCorruptionError:
        raise
    except Exception as exc:
        raise EventIncompleteHistoryError(
            "secure Harness activity reference is unavailable or unauthorized"
        ) from exc
    if not isinstance(validation, SecurePayloadValidation):
        raise EventStoreCorruptionError(
            "secure Harness activity store returned invalid validation evidence"
        )
    if not validation.proves(
        reference.to_dict(),
        tenant_id=tenant_id,
        classification=classification,
    ):
        raise EventIncompleteHistoryError(
            "secure Harness activity reference is not authorized"
        )
    try:
        record = store.resolve_result(
            reference,
            tenant_id=tenant_id,
            classification=classification,
        )
    except EventStoreCorruptionError:
        raise
    except Exception as exc:
        raise EventIncompleteHistoryError(
            "committed Harness activity result is unavailable"
        ) from exc
    if not isinstance(record, HarnessActivityResultRecord):
        raise EventStoreCorruptionError(
            "secure Harness activity store returned an invalid record"
        )
    if record.activity != expected_activity:
        raise EventStoreCorruptionError(
            "committed Harness activity identity does not match history"
        )
    if record.content_checksum != reference.expected_checksum:
        raise EventStoreCorruptionError(
            "committed Harness activity result checksum does not match reference"
        )
    return record


def validate_activity_call_marker(
    payload: Mapping[str, Any],
    *,
    expected_activity: HarnessActivity,
) -> None:
    if not isinstance(payload, Mapping):
        raise EventStoreCorruptionError(
            "Harness worker call marker payload is invalid"
        )
    expected = {
        "worker_type": expected_activity.activity_type,
        "activity_id": expected_activity.activity_id,
        "idempotency_key": expected_activity.idempotency_key,
        "activity_attempt": expected_activity.attempt,
        "activity_contract_version": expected_activity.contract_version,
    }
    for field_name, expected_value in expected.items():
        value = payload.get(field_name)
        if field_name == "activity_attempt" and (
            isinstance(value, bool) or not isinstance(value, int)
        ):
            raise EventStoreCorruptionError(
                "Harness worker call marker activity_attempt is invalid"
            )
        if value != expected_value:
            raise EventStoreCorruptionError(
                f"Harness worker call marker {field_name} conflicts with activity"
            )


def _worker_result_from_dict(value: Mapping[str, Any]) -> HarnessWorkerResult:
    output = value.get("output", {})
    artifacts = value.get("artifacts", ())
    diagnostics = value.get("diagnostics", {})
    metrics = value.get("metrics", {})
    if not isinstance(output, Mapping):
        raise HarnessValidationError("worker result output must be an object")
    if not isinstance(artifacts, list | tuple):
        raise HarnessValidationError("worker result artifacts must be an array")
    if not isinstance(diagnostics, Mapping) or not isinstance(metrics, Mapping):
        raise HarnessValidationError(
            "worker result diagnostics and metrics must be objects"
        )
    error = value.get("error")
    return HarnessWorkerResult(
        status=value.get("status"),
        output=dict(output),
        artifacts=tuple(str(item) for item in artifacts),
        diagnostics=dict(diagnostics),
        metrics=dict(metrics),
        error=None if error is None else str(error),
    )


def _is_checksum(value: str) -> bool:
    if not value.startswith("sha256:"):
        return False
    digest = value.removeprefix("sha256:")
    return len(digest) == 64 and all(
        character in "0123456789abcdef" for character in digest
    )


__all__ = [
    "HARNESS_ACTIVITY_CONTRACT",
    "HARNESS_ACTIVITY_EXTENSION",
    "HARNESS_ACTIVITY_RESULT_SCHEMA",
    "HarnessActivity",
    "HarnessActivityResultRecord",
    "SecureHarnessActivityStorePort",
    "resolve_activity_result",
    "validate_activity_call_marker",
]
