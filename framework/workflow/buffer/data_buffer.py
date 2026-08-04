from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Iterator, Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from enum import StrEnum
from functools import wraps
from threading import RLock
from typing import Any

from framework.shared.attempts import current_attempt_context


DEFAULT_SENSITIVE_KEY_PATTERNS = (
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "access_key",
    "private_key",
    "credential",
    "authorization",
    "client_secret",
)

REDACTED_VALUE = "***REDACTED***"


class DataBufferPermissionError(RuntimeError):
    """Raised when a scoped buffer access violates read/write permissions."""


class DataBufferReadPermissionError(DataBufferPermissionError):
    """Raised when a step reads a key outside its declared data scope."""


class DataBufferWritePermissionError(DataBufferPermissionError):
    """Raised when a step writes a key outside its declared data scope."""


class DataBufferSchemaError(RuntimeError):
    """Raised when a buffer value does not match its registered schema."""


class DataBufferKeyError(RuntimeError):
    """Raised when a required buffer key is missing."""


class StaleWorkflowAttemptError(RuntimeError):
    """Raised when a closed or superseded attempt touches its buffer overlay."""


def _synchronized(method: Any) -> Any:
    @wraps(method)
    def wrapped(self: "ScopedDataBuffer", *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapped


class RedactionStatus(StrEnum):
    NONE = "none"
    REDACTED = "redacted"
    SENSITIVE = "sensitive"


@dataclass(frozen=True)
class StepDataScope:
    step_id: str
    read_keys: set[str] = field(default_factory=set)
    optional_read_keys: set[str] = field(default_factory=set)
    write_keys: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class BufferValueSchema:
    key: str
    value_type: type
    schema_version: str | None = None
    required_fields: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class BufferLineage:
    key: str
    produced_by_step_id: str
    source_keys: list[str] = field(default_factory=list)
    source_steps: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "produced_by_step_id": self.produced_by_step_id,
            "source_keys": list(self.source_keys),
            "source_steps": list(self.source_steps),
            "metadata": deepcopy(self.metadata),
        }


@dataclass(frozen=True)
class BufferWriteRecord:
    key: str
    step_id: str
    previous_hash: str | None
    new_hash: str
    value_type: str
    schema_version: str | None
    written_at: str
    lineage: dict[str, Any] = field(default_factory=dict)
    redaction_status: RedactionStatus = RedactionStatus.NONE

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "step_id": self.step_id,
            "previous_hash": self.previous_hash,
            "new_hash": self.new_hash,
            "value_type": self.value_type,
            "schema_version": self.schema_version,
            "written_at": self.written_at,
            "lineage": deepcopy(self.lineage),
            "redaction_status": self.redaction_status.value,
        }


@dataclass(frozen=True)
class BufferDiff:
    added: dict[str, Any]
    modified: dict[str, dict[str, Any]]
    deleted: dict[str, Any]

    @property
    def changed(self) -> dict[str, dict[str, Any]]:
        return self.modified

    @property
    def removed(self) -> dict[str, Any]:
        return self.deleted

    def to_dict(self) -> dict[str, Any]:
        """Return the historical artifact shape used by run inspection."""

        return {
            "added": deepcopy(self.added),
            "changed": _legacy_changed_payload(self.modified),
            "removed": deepcopy(self.deleted),
        }

    def to_governance_dict(self) -> dict[str, Any]:
        return {
            "added": deepcopy(self.added),
            "modified": deepcopy(self.modified),
            "deleted": deepcopy(self.deleted),
        }


DataBufferDiff = BufferDiff


@dataclass(frozen=True)
class DataBufferSnapshot:
    values: dict[str, Any]
    lineage: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    snapshot_hash: str | None = None
    redacted: bool = True
    snapshot_version: int = 0

    def __getitem__(self, key: str) -> Any:
        return self.values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.values)

    def __len__(self) -> int:
        return len(self.values)

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self.values)

    def lineage_to_dict(self) -> dict[str, list[dict[str, Any]]]:
        return deepcopy(self.lineage)


class ScopedDataBuffer:
    """Workflow runtime's governed shared data layer."""

    def __init__(
        self,
        initial_values: Mapping[str, Any] | None = None,
        *,
        sensitive_keys: Iterable[str] | None = None,
    ) -> None:
        self._lock = RLock()
        self._data: dict[str, Any] = {}
        self._scopes: dict[str, StepDataScope] = {}
        self._write_history: list[BufferWriteRecord] = []
        self._lineage: dict[str, BufferLineage] = {}
        self._legacy_lineage: dict[str, list[dict[str, Any]]] = {}
        self._schema_registry: dict[str, BufferValueSchema] = {}
        self._sensitive_keys: set[str] = {str(key) for key in sensitive_keys or ()}
        self._snapshot_version = 0
        self._adhoc_scope_index = 0
        self._attempt_fences: dict[str, tuple[int, str]] = {}

        for key, value in (initial_values or {}).items():
            self.seed_request_key(str(key), value)

    @_synchronized
    def register_scope(self, scope: StepDataScope) -> None:
        self._scopes[scope.step_id] = StepDataScope(
            step_id=scope.step_id,
            read_keys={str(key) for key in scope.read_keys},
            optional_read_keys={str(key) for key in scope.optional_read_keys},
            write_keys={str(key) for key in scope.write_keys},
        )

    @_synchronized
    def register_scopes(self, scopes: Iterable[StepDataScope]) -> None:
        for scope in scopes:
            self.register_scope(scope)

    @_synchronized
    def register_schema(self, schema: BufferValueSchema) -> None:
        self._schema_registry[schema.key] = schema

    @_synchronized
    def seed_request_key(self, key: str, value: Any) -> None:
        self._data[key] = deepcopy(value)
        self._lineage[key] = BufferLineage(
            key=key,
            produced_by_step_id="__request__",
        )
        self._snapshot_version += 1

    @_synchronized
    def read(
        self,
        key: str | None = None,
        *,
        step_id: str | None = None,
        default: Any = None,
        required: bool = True,
    ) -> Any:
        actual_key = _require_key(key)
        if step_id is not None:
            self._assert_can_read(step_id, actual_key)

        if actual_key not in self._data:
            if required:
                raise DataBufferKeyError(f"Required buffer key does not exist: {actual_key}")
            return default

        return deepcopy(self._data[actual_key])

    @_synchronized
    def write(
        self,
        key: str | None = None,
        value: Any = None,
        lineage: dict[str, Any] | None = None,
        *,
        step_id: str | None = None,
        source_keys: list[str] | None = None,
        schema_version: str | None = None,
        lineage_metadata: dict[str, Any] | None = None,
    ) -> None:
        actual_key = _require_key(key)
        if step_id is not None:
            self._assert_can_write(step_id, actual_key)
        self._validate_schema(key=actual_key, value=value, schema_version=schema_version)

        previous_hash = self._hash_value(self._data[actual_key]) if actual_key in self._data else None
        new_hash = self._hash_value(value)
        self._data[actual_key] = deepcopy(value)

        metadata = deepcopy(lineage_metadata or {})
        if lineage is not None:
            metadata.setdefault("legacy_lineage", deepcopy(lineage))

        actual_step_id = step_id or _lineage_step_id(lineage) or "__direct_write__"
        actual_source_keys = [str(key) for key in source_keys or []]
        built_lineage = self._build_lineage(
            key=actual_key,
            step_id=actual_step_id,
            source_keys=actual_source_keys,
            metadata=metadata,
        )
        self._lineage[actual_key] = built_lineage
        if lineage is not None:
            self._legacy_lineage.setdefault(actual_key, []).append(deepcopy(lineage))

        record = BufferWriteRecord(
            key=actual_key,
            step_id=actual_step_id,
            previous_hash=previous_hash,
            new_hash=new_hash,
            value_type=type(value).__name__,
            schema_version=schema_version,
            written_at=self._now_iso(),
            lineage={
                "source_keys": list(built_lineage.source_keys),
                "source_steps": list(built_lineage.source_steps),
                "metadata": deepcopy(built_lineage.metadata),
            },
            redaction_status=self._redaction_status_for_key(actual_key),
        )
        self._write_history.append(record)
        self._snapshot_version += 1

    @_synchronized
    def delete(self, *, step_id: str | None = None, key: str) -> None:
        if step_id is not None:
            self._assert_can_write(step_id, key)

        if key not in self._data:
            return

        previous_hash = self._hash_value(self._data[key])
        del self._data[key]
        self._lineage.pop(key, None)
        self._legacy_lineage.pop(key, None)
        self._write_history.append(
            BufferWriteRecord(
                key=key,
                step_id=step_id or "__direct_delete__",
                previous_hash=previous_hash,
                new_hash=stable_hash(None),
                value_type="deleted",
                schema_version=None,
                written_at=self._now_iso(),
                lineage={"operation": "delete"},
                redaction_status=self._redaction_status_for_key(key),
            )
        )
        self._snapshot_version += 1

    @_synchronized
    def exists(self, key: str) -> bool:
        return key in self._data

    @_synchronized
    def snapshot(self, *, redacted: bool = True) -> DataBufferSnapshot:
        values = {
            key: self._snapshot_value(key, value, redacted=redacted)
            for key, value in self._data.items()
        }
        return DataBufferSnapshot(
            values=deepcopy(values),
            lineage=self._lineage_snapshot(),
            snapshot_hash=stable_hash(values),
            redacted=redacted,
            snapshot_version=self._snapshot_version,
        )

    @_synchronized
    def snapshot_hash(self, *, redacted: bool = True) -> str:
        return stable_hash(self.snapshot(redacted=redacted).to_dict())

    @_synchronized
    def diff(self, before_snapshot: Mapping[str, Any] | DataBufferSnapshot) -> BufferDiff:
        if isinstance(before_snapshot, DataBufferSnapshot):
            before = before_snapshot.to_dict()
        else:
            before = dict(before_snapshot)
        return self.diff_snapshots(before, self.snapshot(redacted=False).to_dict())

    @staticmethod
    def diff_snapshots(
        before: Mapping[str, Any],
        after: Mapping[str, Any],
    ) -> BufferDiff:
        before_values = dict(before)
        after_values = dict(after)
        before_keys = set(before_values)
        after_keys = set(after_values)

        added = {
            key: deepcopy(after_values[key])
            for key in sorted(after_keys - before_keys)
        }
        deleted = {
            key: deepcopy(before_values[key])
            for key in sorted(before_keys - after_keys)
        }
        modified: dict[str, dict[str, Any]] = {}

        for key in sorted(before_keys & after_keys):
            before_hash = stable_hash(before_values[key])
            after_hash = stable_hash(after_values[key])
            if before_hash == after_hash:
                continue
            modified[key] = {
                "before": deepcopy(before_values[key]),
                "after": deepcopy(after_values[key]),
                "before_hash": before_hash,
                "after_hash": after_hash,
            }

        return BufferDiff(added=added, modified=modified, deleted=deleted)

    def scoped(self, step_id: str) -> StepScopedDataBufferView:
        return StepScopedDataBufferView(step_id=step_id, buffer=self)

    @_synchronized
    def begin_attempt(
        self,
        step_id: str,
        *,
        owner_id: str,
    ) -> "AttemptDataBufferOverlay":
        normalized_owner_id = str(owner_id).strip()
        if not normalized_owner_id:
            raise ValueError("owner_id is required")
        if step_id not in self._scopes:
            raise DataBufferPermissionError(
                f"No data scope registered for step: {step_id}"
            )
        previous = self._attempt_fences.get(step_id)
        fencing_token = 1 if previous is None else previous[0] + 1
        self._attempt_fences[step_id] = (fencing_token, normalized_owner_id)
        return AttemptDataBufferOverlay(
            step_id=step_id,
            buffer=self,
            fencing_token=fencing_token,
            owner_id=normalized_owner_id,
            snapshot_values=deepcopy(self._data),
        )

    @_synchronized
    def is_current_attempt(
        self,
        step_id: str,
        fencing_token: int,
        owner_id: str,
    ) -> bool:
        return self._attempt_fences.get(step_id) == (fencing_token, owner_id)

    @_synchronized
    def abandon_attempt(
        self,
        step_id: str,
        *,
        lease_generation: int,
        owner_id: str,
    ) -> bool:
        """Invalidate a lease when admitted work never reaches physical start."""

        expected = (lease_generation, str(owner_id).strip())
        if self._attempt_fences.get(step_id) != expected:
            return False
        self._attempt_fences.pop(step_id, None)
        return True

    @_synchronized
    def scope(
        self,
        read_keys: list[str] | set[str],
        write_keys: list[str] | set[str],
        *,
        optional_read_keys: list[str] | set[str] | None = None,
        step_id: str | None = None,
    ) -> StepScopedDataBufferView:
        actual_step_id = step_id or self._next_adhoc_scope_id()
        self.register_scope(
            StepDataScope(
                step_id=actual_step_id,
                read_keys={str(key) for key in read_keys},
                optional_read_keys={str(key) for key in optional_read_keys or set()},
                write_keys={str(key) for key in write_keys},
            )
        )
        return self.scoped(actual_step_id)

    @_synchronized
    def lineage(self, key: str | None = None) -> dict[str, list[dict[str, Any]]] | list[dict[str, Any]]:
        if key is None:
            return deepcopy(self._legacy_lineage)
        return deepcopy(self._legacy_lineage.get(key, []))

    def _lineage_snapshot(self) -> dict[str, list[dict[str, Any]]]:
        return deepcopy(self._legacy_lineage)

    @_synchronized
    def get_lineage(self, key: str) -> BufferLineage | None:
        lineage = self._lineage.get(key)
        return deepcopy(lineage) if lineage is not None else None

    @_synchronized
    def write_history(self, key: str | None = None) -> list[BufferWriteRecord]:
        records = self._write_history
        if key is not None:
            records = [record for record in records if record.key == key]
        return list(records)

    @_synchronized
    def redact(self, policy: dict[str, Any] | None = None) -> dict[str, Any]:
        policy = policy or {}
        redacted_keys = {str(key) for key in policy.get("redacted_keys", [])}
        replacement = str(policy.get("replacement", "[REDACTED]"))
        return {
            key: replacement if key in redacted_keys or self._is_sensitive_key(key) else deepcopy(value)
            for key, value in self._data.items()
        }

    def _assert_can_read(self, step_id: str, key: str) -> None:
        scope = self._scopes.get(step_id)
        if scope is None:
            raise DataBufferReadPermissionError(
                f"No data scope registered for step: {step_id}"
            )

        allowed = scope.read_keys | scope.optional_read_keys
        if key not in allowed:
            raise DataBufferReadPermissionError(
                f"Step {step_id} cannot read undeclared key: {key}; read key is not allowed"
            )

    def _assert_can_write(self, step_id: str, key: str) -> None:
        scope = self._scopes.get(step_id)
        if scope is None:
            raise DataBufferWritePermissionError(
                f"No data scope registered for step: {step_id}"
            )

        if key not in scope.write_keys:
            raise DataBufferWritePermissionError(
                f"Step {step_id} cannot write undeclared key: {key}; write key is not allowed"
            )

    def _validate_schema(
        self,
        *,
        key: str,
        value: Any,
        schema_version: str | None,
    ) -> None:
        schema = self._schema_registry.get(key)
        if schema is None:
            return

        if not isinstance(value, schema.value_type):
            raise DataBufferSchemaError(
                f"Buffer key {key} expects {schema.value_type.__name__}, "
                f"got {type(value).__name__}"
            )

        if schema.required_fields and isinstance(value, Mapping):
            missing = schema.required_fields - {str(item) for item in value.keys()}
            if missing:
                raise DataBufferSchemaError(
                    f"Buffer key {key} missing required fields: {sorted(missing)}"
                )

        if schema.schema_version and schema_version and schema.schema_version != schema_version:
            raise DataBufferSchemaError(
                f"Buffer key {key} schema version mismatch: "
                f"expected {schema.schema_version}, got {schema_version}"
            )

    def _build_lineage(
        self,
        *,
        key: str,
        step_id: str,
        source_keys: list[str],
        metadata: dict[str, Any],
    ) -> BufferLineage:
        source_steps: list[str] = []
        for source_key in source_keys:
            source_lineage = self._lineage.get(source_key)
            if source_lineage is not None:
                source_steps.append(source_lineage.produced_by_step_id)

        return BufferLineage(
            key=key,
            produced_by_step_id=step_id,
            source_keys=list(source_keys),
            source_steps=sorted(set(source_steps)),
            metadata=deepcopy(metadata),
        )

    def _hash_value(self, value: Any) -> str:
        return stable_hash(value)

    def _snapshot_value(self, key: str, value: Any, *, redacted: bool) -> Any:
        if redacted and self._is_sensitive_key(key):
            return self._redact_value(value)
        return deepcopy(value)

    def _is_sensitive_key(self, key: str) -> bool:
        normalized = key.lower()
        if key in self._sensitive_keys:
            return True
        return any(pattern in normalized for pattern in DEFAULT_SENSITIVE_KEY_PATTERNS)

    def _redact_value(self, value: Any) -> str:
        _ = value
        return REDACTED_VALUE

    def _redaction_status_for_key(self, key: str) -> RedactionStatus:
        if self._is_sensitive_key(key):
            return RedactionStatus.SENSITIVE
        return RedactionStatus.NONE

    def _next_adhoc_scope_id(self) -> str:
        self._adhoc_scope_index += 1
        return f"__scope_{self._adhoc_scope_index}__"

    def _now_iso(self) -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class DataBuffer(ScopedDataBuffer):
    """Backward-compatible name for the governed workflow data buffer."""


@dataclass
class StepScopedDataBufferView:
    step_id: str
    buffer: ScopedDataBuffer

    def read(self, key: str, default: Any = None, required: bool = True) -> Any:
        return self.buffer.read(
            step_id=self.step_id,
            key=key,
            default=default,
            required=required,
        )

    def write(
        self,
        key: str,
        value: Any,
        lineage: dict[str, Any] | None = None,
        *,
        source_keys: list[str] | None = None,
        schema_version: str | None = None,
        lineage_metadata: dict[str, Any] | None = None,
    ) -> None:
        self.buffer.write(
            step_id=self.step_id,
            key=key,
            value=value,
            lineage=lineage,
            source_keys=source_keys,
            schema_version=schema_version,
            lineage_metadata=lineage_metadata,
        )

    def delete(self, key: str) -> None:
        self.buffer.delete(step_id=self.step_id, key=key)

    def exists(self, key: str) -> bool:
        scope = self.buffer._scopes.get(self.step_id)
        if scope is None:
            raise DataBufferReadPermissionError(
                f"No data scope registered for step: {self.step_id}"
            )
        if key not in scope.read_keys and key not in scope.optional_read_keys and key not in scope.write_keys:
            raise DataBufferReadPermissionError(
                f"Step {self.step_id} cannot access undeclared key: {key}; key is not in scope"
            )
        return self.buffer.exists(key)

    def list_allowed_reads(self) -> list[str]:
        scope = self.buffer._scopes.get(self.step_id)
        if scope is None:
            return []
        return sorted(scope.read_keys)

    def list_optional_reads(self) -> list[str]:
        scope = self.buffer._scopes.get(self.step_id)
        if scope is None:
            return []
        return sorted(scope.optional_read_keys)

    def list_allowed_writes(self) -> list[str]:
        scope = self.buffer._scopes.get(self.step_id)
        if scope is None:
            return []
        return sorted(scope.write_keys)


@dataclass(frozen=True)
class _AttemptBufferMutation:
    operation: str
    key: str
    value: Any = None
    lineage: dict[str, Any] | None = None
    source_keys: list[str] | None = None
    schema_version: str | None = None
    lineage_metadata: dict[str, Any] | None = None


class AttemptDataBufferCommitTransaction:
    """Hold a buffer publication lock until its durable terminal fact exists."""

    def __init__(
        self,
        *,
        overlay: "AttemptDataBufferOverlay",
        state_before: tuple[Any, ...],
    ) -> None:
        self._overlay = overlay
        self._state_before = state_before
        self._active = True

    def rollback(self) -> None:
        if not self._active:
            return
        try:
            (
                self._overlay.buffer._data,
                self._overlay.buffer._lineage,
                self._overlay.buffer._legacy_lineage,
                self._overlay.buffer._write_history,
                self._overlay.buffer._snapshot_version,
            ) = self._state_before
        finally:
            self._release()

    def complete(self) -> None:
        if not self._active:
            return
        self._release()

    def _release(self) -> None:
        self._active = False
        self._overlay.buffer._lock.release()
        self._overlay._overlay_lock.release()


class AttemptDataBufferOverlay(StepScopedDataBufferView):
    """Private, fenced write set for one Workflow step attempt."""

    def __init__(
        self,
        *,
        step_id: str,
        buffer: ScopedDataBuffer,
        fencing_token: int,
        owner_id: str,
        snapshot_values: Mapping[str, Any],
    ) -> None:
        super().__init__(step_id=step_id, buffer=buffer)
        self.fencing_token = fencing_token
        self.owner_id = owner_id
        self._snapshot_values = deepcopy(dict(snapshot_values))
        self._mutations: list[_AttemptBufferMutation] = []
        self._closed = False
        self._overlay_lock = RLock()

    @property
    def closed(self) -> bool:
        with self._overlay_lock:
            return self._closed

    def read(self, key: str, default: Any = None, required: bool = True) -> Any:
        with self._overlay_lock:
            self._ensure_open()
            self.buffer._assert_can_read(self.step_id, key)
            if key not in self._snapshot_values:
                if required:
                    raise DataBufferKeyError(
                        f"Required buffer key does not exist: {key}"
                    )
                return deepcopy(default)
            return deepcopy(self._snapshot_values[key])

    def write(
        self,
        key: str,
        value: Any,
        lineage: dict[str, Any] | None = None,
        *,
        source_keys: list[str] | None = None,
        schema_version: str | None = None,
        lineage_metadata: dict[str, Any] | None = None,
    ) -> None:
        with self._overlay_lock:
            self._ensure_open()
            self.buffer._assert_can_write(self.step_id, key)
            self.buffer._validate_schema(
                key=key,
                value=value,
                schema_version=schema_version,
            )
            self._snapshot_values[key] = deepcopy(value)
            self._mutations.append(
                _AttemptBufferMutation(
                    operation="write",
                    key=key,
                    value=deepcopy(value),
                    lineage=deepcopy(lineage),
                    source_keys=list(source_keys or []),
                    schema_version=schema_version,
                    lineage_metadata=deepcopy(lineage_metadata),
                )
            )

    def delete(self, key: str) -> None:
        with self._overlay_lock:
            self._ensure_open()
            self.buffer._assert_can_write(self.step_id, key)
            self._snapshot_values.pop(key, None)
            self._mutations.append(
                _AttemptBufferMutation(operation="delete", key=key)
            )

    def exists(self, key: str) -> bool:
        with self._overlay_lock:
            self._ensure_open()
            scope = self.buffer._scopes.get(self.step_id)
            if scope is None:
                raise DataBufferReadPermissionError(
                    f"No data scope registered for step: {self.step_id}"
                )
            if (
                key not in scope.read_keys
                and key not in scope.optional_read_keys
                and key not in scope.write_keys
            ):
                raise DataBufferReadPermissionError(
                    f"Step {self.step_id} cannot access undeclared key: {key}; "
                    "key is not in scope"
                )
            return key in self._snapshot_values

    def close(self) -> None:
        with self._overlay_lock:
            self._closed = True

    def commit(self) -> None:
        """Atomically publish the staged mutations when this fence still owns the step."""

        transaction = self.begin_commit()
        transaction.complete()

    def begin_commit(self) -> AttemptDataBufferCommitTransaction:
        """Stage publication while retaining an atomic rollback boundary."""

        self._overlay_lock.acquire()
        self.buffer._lock.acquire()
        state_before: tuple[Any, ...] | None = None
        try:
            self._ensure_open()
            if not self.buffer.is_current_attempt(
                self.step_id,
                self.fencing_token,
                self.owner_id,
            ):
                self._closed = True
                raise StaleWorkflowAttemptError(
                    f"workflow attempt fence is stale for step {self.step_id}"
                )

            state_before = (
                deepcopy(self.buffer._data),
                deepcopy(self.buffer._lineage),
                deepcopy(self.buffer._legacy_lineage),
                list(self.buffer._write_history),
                self.buffer._snapshot_version,
            )
            for mutation in self._mutations:
                if mutation.operation == "delete":
                    self.buffer.delete(step_id=self.step_id, key=mutation.key)
                else:
                    self.buffer.write(
                        step_id=self.step_id,
                        key=mutation.key,
                        value=mutation.value,
                        lineage=mutation.lineage,
                        source_keys=mutation.source_keys,
                        schema_version=mutation.schema_version,
                        lineage_metadata=mutation.lineage_metadata,
                    )
            if self._mutations:
                self.buffer._snapshot_version = state_before[4] + 1
            self._closed = True
            return AttemptDataBufferCommitTransaction(
                overlay=self,
                state_before=state_before,
            )
        except BaseException:  # noqa: BLE001 - restore before propagating
            if state_before is not None:
                (
                    self.buffer._data,
                    self.buffer._lineage,
                    self.buffer._legacy_lineage,
                    self.buffer._write_history,
                    self.buffer._snapshot_version,
                ) = state_before
            self._closed = True
            self.buffer._lock.release()
            self._overlay_lock.release()
            raise

    def _ensure_open(self) -> None:
        if self._closed or not self.buffer.is_current_attempt(
            self.step_id,
            self.fencing_token,
            self.owner_id,
        ):
            self._closed = True
            raise StaleWorkflowAttemptError(
                f"workflow attempt buffer is closed or stale for step {self.step_id}"
            )
        context = current_attempt_context()
        if context is not None:
            context.raise_if_cancelled()
            context.raise_if_indeterminate()


def step_scope_from_spec(step: Any) -> StepDataScope:
    return StepDataScope(
        step_id=str(step.step_id),
        read_keys={str(key) for key in getattr(step, "read_keys", [])},
        optional_read_keys={
            str(key)
            for key in getattr(step, "metadata", {}).get("optional_read_keys", [])
        },
        write_keys={str(key) for key in getattr(step, "write_keys", [])},
    )


def stable_json_dumps(value: Any) -> str:
    return json.dumps(
        _stable_json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def stable_hash(value: Any) -> str:
    raw = stable_json_dumps(value)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _stable_json_value(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _stable_json_value(asdict(value))
    if isinstance(value, Mapping):
        return {
            str(key): _stable_json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _stable_json_value(model_dump(mode="json"))
    if isinstance(value, (list, tuple)):
        return [_stable_json_value(item) for item in value]
    if isinstance(value, set):
        return [_stable_json_value(item) for item in sorted(value, key=str)]
    try:
        json.dumps(value)
    except TypeError:
        return str(value)
    return value


def _require_key(key: str | None) -> str:
    if key is None:
        raise TypeError("buffer key is required")
    return str(key)


def _lineage_step_id(lineage: dict[str, Any] | None) -> str | None:
    if not isinstance(lineage, dict):
        return None
    step_id = lineage.get("step_id")
    return str(step_id) if step_id is not None else None


def _legacy_changed_payload(modified: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    payload: dict[str, dict[str, Any]] = {}
    for key, value in modified.items():
        payload[key] = {
            "previous": deepcopy(value.get("before")),
            "current": deepcopy(value.get("after")),
        }
    return payload


def _looks_sensitive_key(key: str) -> bool:
    key_lower = key.casefold()
    return any(token in key_lower for token in DEFAULT_SENSITIVE_KEY_PATTERNS)
