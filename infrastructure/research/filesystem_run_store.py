from __future__ import annotations

import copy
import hmac
import json
import os
import re
import stat
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from business.research.ports.run_store import (
    ResearchRunRecord,
    ResearchRunStoreConflictError,
    ResearchRunStoreCorruptionError,
    ResearchRunStoreError,
    ResearchRunStoreReason,
    ResearchRunStoreUnavailableError,
    ResearchRunStoreValidationError,
)
from infrastructure.research.diagnostics import emit_research_persistence_diagnostic


RESEARCH_RUN_RECORD_SCHEMA_VERSION = "newsroom.research_run_record.v1"
RESEARCH_RUN_LATEST_INDEX_SCHEMA_VERSION = "newsroom.research_run_latest_index.v1"
DEFAULT_RESEARCH_RUN_RECORD_MAX_BYTES = 16_777_216

_LATEST_INDEX_MAX_BYTES = 65_536
_MIN_RECORD_BYTES = 1_024
_MAX_RECORD_BYTES = 536_870_912
_MAX_ID_BYTES = 4_096
_CHECKSUM = re.compile(r"^sha256:[0-9a-f]{64}$")
_RECORD_FILENAME = re.compile(r"^[0-9a-f]{64}\.json$")
_PATH_LOCKS_GUARD = threading.Lock()
_PATH_LOCKS: dict[Path, threading.RLock] = {}
_RECORD_FIELDS = {
    "schema_version",
    "run_id",
    "paper_id",
    "commit_generation",
    "committed_at",
    "result",
    "result_checksum",
    "checksum",
}
_INDEX_FIELDS = {
    "schema_version",
    "paper_id",
    "run_id",
    "commit_generation",
    "committed_at",
    "record_checksum",
    "checksum",
}
_RESULT_PAPER_ID_PATHS = (
    ("analysis", "paper_id"),
    ("quality", "target_id"),
    ("paper_card", "paper_id"),
    ("reader_payload", "paper", "paper_id"),
    ("reader_payload", "document", "paper_id"),
    ("reader_payload", "analysis", "paper_id"),
    ("reader_payload", "evidence", "paper_id"),
    ("rag_context", "paper_id"),
    ("rag_context", "goal", "paper_id"),
    ("reader_issue", "paper_id"),
)

ResearchResultDecoder = Callable[[dict[str, Any]], Any]


@dataclass(frozen=True, slots=True)
class _PersistedRecord:
    run_id: str
    paper_id: str
    commit_generation: int
    committed_at: str
    result: dict[str, Any]
    result_checksum: str
    checksum: str

    @property
    def commit_key(self) -> tuple[int, str, str]:
        return (self.commit_generation, self.committed_at, self.run_id)


@dataclass(frozen=True, slots=True)
class _PersistedIndex:
    paper_id: str
    run_id: str
    commit_generation: int
    committed_at: str
    record_checksum: str
    checksum: str


class FilesystemResearchRunStore:
    """Single-host, checksum-verified storage for complete Research results."""

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        result_decoder: ResearchResultDecoder,
        max_record_bytes: int = DEFAULT_RESEARCH_RUN_RECORD_MAX_BYTES,
    ) -> None:
        self._root = _validated_root(root)
        self._result_decoder = _validated_decoder(result_decoder)
        self._max_record_bytes = _validated_max_bytes(max_record_bytes)
        self._records_root = self._root / "records"
        self._latest_root = self._root / "latest"
        self._lock_path = self._root / ".research-run-store.lock"
        self._lock = _path_lock(self._root)
        _assert_descendant(self._root, self._records_root)
        _assert_descendant(self._root, self._latest_root)
        _assert_descendant(self._root, self._lock_path)

    @property
    def root(self) -> Path:
        return self._root

    @property
    def records_root(self) -> Path:
        return self._records_root

    @property
    def latest_root(self) -> Path:
        return self._latest_root

    @property
    def max_record_bytes(self) -> int:
        return self._max_record_bytes

    def save(self, record: ResearchRunRecord) -> None:
        run_id = record.run_id if isinstance(record, ResearchRunRecord) else None
        paper_id = record.paper_id if isinstance(record, ResearchRunRecord) else None
        try:
            self._save(record)
        except Exception as exc:
            emit_research_persistence_diagnostic(
                component="run_store",
                operation="run_save",
                outcome="failed",
                reason=_run_store_failure_reason(exc),
                run_id=run_id,
                paper_id=paper_id,
            )
            raise
        emit_research_persistence_diagnostic(
            component="run_store",
            operation="run_save",
            outcome="succeeded",
            reason="completed",
            run_id=run_id,
            paper_id=paper_id,
        )

    def _save(self, record: ResearchRunRecord) -> None:
        if not isinstance(record, ResearchRunRecord):
            raise ResearchRunStoreValidationError(ResearchRunStoreReason.INVALID_RECORD)
        run_id = _validated_identity(record.run_id)
        paper_id = _validated_identity(record.paper_id)
        result = _result_projection(record.result)
        if not _result_identity_matches(result, run_id=run_id, paper_id=paper_id):
            raise ResearchRunStoreValidationError(
                ResearchRunStoreReason.IDENTITY_MISMATCH
            )
        result_checksum = _state_checksum(result)
        self._validate_result_before_save(
            result,
            run_id=run_id,
            paper_id=paper_id,
            result_checksum=result_checksum,
        )

        with self._operation_lock():
            current_index = self._read_index(paper_id)
            records = self._scan_records()
            existing = next(
                (item for item in records if item.run_id == run_id),
                None,
            )
            if existing is not None:
                if (
                    existing.paper_id != paper_id
                    or not _constant_time_equal(
                        existing.result_checksum,
                        result_checksum,
                    )
                    or existing.result != result
                ):
                    raise ResearchRunStoreConflictError(
                        ResearchRunStoreReason.IDENTITY_CONFLICT
                    )
                committed = existing
            else:
                generation = 1 + max(
                    (
                        item.commit_generation
                        for item in records
                        if item.paper_id == paper_id
                    ),
                    default=0,
                )
                committed = self._commit_record(
                    run_id=run_id,
                    paper_id=paper_id,
                    generation=generation,
                    result=result,
                    result_checksum=result_checksum,
                )
                records.append(committed)

            self._synchronize_latest_index(
                paper_id,
                records=records,
                current=current_index,
            )

    def get_by_run_id(self, run_id: str) -> ResearchRunRecord | None:
        try:
            result = self._get_by_run_id(run_id)
        except Exception as exc:
            emit_research_persistence_diagnostic(
                component="run_store",
                operation="run_get",
                outcome="failed",
                reason=_run_store_failure_reason(exc),
                run_id=run_id,
            )
            raise
        emit_research_persistence_diagnostic(
            component="run_store",
            operation="run_get",
            outcome="not_found" if result is None else "succeeded",
            reason="not_found" if result is None else "completed",
            run_id=run_id,
            paper_id=result.paper_id if result is not None else None,
        )
        return result

    def _get_by_run_id(self, run_id: str) -> ResearchRunRecord | None:
        expected_run_id = _validated_identity(run_id)
        with self._operation_lock():
            persisted = self._read_record_path(
                self._record_path(expected_run_id),
                expected_run_id=expected_run_id,
            )
        if persisted is None:
            return None
        return self._decode_record(persisted)

    def get_latest_by_paper_id(self, paper_id: str) -> ResearchRunRecord | None:
        try:
            result = self._get_latest_by_paper_id(paper_id)
        except Exception as exc:
            emit_research_persistence_diagnostic(
                component="run_store",
                operation="run_get_latest",
                outcome="failed",
                reason=_run_store_failure_reason(exc),
                paper_id=paper_id,
            )
            raise
        emit_research_persistence_diagnostic(
            component="run_store",
            operation="run_get_latest",
            outcome="not_found" if result is None else "succeeded",
            reason="not_found" if result is None else "completed",
            run_id=result.run_id if result is not None else None,
            paper_id=paper_id,
        )
        return result

    def _get_latest_by_paper_id(self, paper_id: str) -> ResearchRunRecord | None:
        expected_paper_id = _validated_identity(paper_id)
        with self._operation_lock():
            current = self._read_index(expected_paper_id)
            records = self._scan_records()
            latest = self._synchronize_latest_index(
                expected_paper_id,
                records=records,
                current=current,
            )
        if latest is None:
            return None
        return self._decode_record(latest)

    def list_by_paper_id(self, paper_id: str) -> list[ResearchRunRecord]:
        try:
            result = self._list_by_paper_id(paper_id)
        except Exception as exc:
            emit_research_persistence_diagnostic(
                component="run_store",
                operation="run_list_by_paper",
                outcome="failed",
                reason=_run_store_failure_reason(exc),
                paper_id=paper_id,
            )
            raise
        emit_research_persistence_diagnostic(
            component="run_store",
            operation="run_list_by_paper",
            outcome="not_found" if not result else "succeeded",
            reason="not_found" if not result else "completed",
            run_id=result[0].run_id if result else None,
            paper_id=paper_id,
        )
        return result

    def _list_by_paper_id(self, paper_id: str) -> list[ResearchRunRecord]:
        expected_paper_id = _validated_identity(paper_id)
        with self._operation_lock():
            current = self._read_index(expected_paper_id)
            records = self._scan_records()
            self._synchronize_latest_index(
                expected_paper_id,
                records=records,
                current=current,
            )
            matching = sorted(
                (
                    record
                    for record in records
                    if record.paper_id == expected_paper_id
                ),
                key=lambda record: record.commit_key,
                reverse=True,
            )
        return [self._decode_record(record) for record in matching]

    @contextmanager
    def _operation_lock(self) -> Iterator[None]:
        with self._lock:
            _ensure_directory(self._root)
            _assert_descendant(self._root, self._lock_path)
            with _exclusive_file_lock(self._lock_path):
                _ensure_directory(self._records_root)
                _ensure_directory(self._latest_root)
                _assert_descendant(self._root, self._records_root)
                _assert_descendant(self._root, self._latest_root)
                yield

    def _commit_record(
        self,
        *,
        run_id: str,
        paper_id: str,
        generation: int,
        result: dict[str, Any],
        result_checksum: str,
    ) -> _PersistedRecord:
        unsigned = {
            "schema_version": RESEARCH_RUN_RECORD_SCHEMA_VERSION,
            "run_id": run_id,
            "paper_id": paper_id,
            "commit_generation": generation,
            "committed_at": _utc_now(),
            "result": result,
            "result_checksum": result_checksum,
        }
        state = {**unsigned, "checksum": _state_checksum(unsigned)}
        encoded = _encoded_json(
            state,
            max_bytes=self._max_record_bytes,
            too_large_reason=ResearchRunStoreReason.RECORD_TOO_LARGE,
        )
        path = self._record_path(run_id)
        _write_atomic(path, encoded)
        committed = self._read_record_path(path, expected_run_id=run_id)
        if committed is None or not _constant_time_equal(
            committed.checksum,
            state["checksum"],
        ):
            raise ResearchRunStoreCorruptionError(
                ResearchRunStoreReason.CHECKSUM_INVALID
            )
        return committed

    def _scan_records(self) -> list[_PersistedRecord]:
        _assert_descendant(self._root, self._records_root)
        if not _directory_exists(self._records_root):
            return []
        try:
            paths = sorted(self._records_root.iterdir(), key=lambda item: item.name)
        except OSError:
            raise ResearchRunStoreUnavailableError(
                ResearchRunStoreReason.FILESYSTEM_UNAVAILABLE
            ) from None

        records: list[_PersistedRecord] = []
        generations: dict[tuple[str, int], str] = {}
        for path in paths:
            if _RECORD_FILENAME.fullmatch(path.name) is None:
                continue
            persisted = self._read_record_path(path)
            if persisted is None:
                continue
            generation_key = (persisted.paper_id, persisted.commit_generation)
            previous_run_id = generations.get(generation_key)
            if previous_run_id is not None and previous_run_id != persisted.run_id:
                raise ResearchRunStoreCorruptionError(
                    ResearchRunStoreReason.IDENTITY_MISMATCH
                )
            generations[generation_key] = persisted.run_id
            records.append(persisted)
        return records

    def _read_record_path(
        self,
        path: Path,
        *,
        expected_run_id: str | None = None,
    ) -> _PersistedRecord | None:
        _assert_descendant(self._root, path)
        state = _read_json_file(path, max_bytes=self._max_record_bytes)
        if state is None:
            return None
        if set(state) != _RECORD_FIELDS:
            raise ResearchRunStoreCorruptionError(ResearchRunStoreReason.SCHEMA_INVALID)
        if state.get("schema_version") != RESEARCH_RUN_RECORD_SCHEMA_VERSION:
            raise ResearchRunStoreCorruptionError(
                ResearchRunStoreReason.SCHEMA_UNSUPPORTED
            )

        run_id = _corrupt_identity(state.get("run_id"))
        paper_id = _corrupt_identity(state.get("paper_id"))
        if expected_run_id is not None and run_id != expected_run_id:
            raise ResearchRunStoreCorruptionError(
                ResearchRunStoreReason.IDENTITY_MISMATCH
            )
        if path.name != _hashed_filename(run_id):
            raise ResearchRunStoreCorruptionError(
                ResearchRunStoreReason.IDENTITY_MISMATCH
            )
        generation = _corrupt_generation(state.get("commit_generation"))
        committed_at = _corrupt_timestamp(state.get("committed_at"))
        result = state.get("result")
        if not isinstance(result, dict):
            raise ResearchRunStoreCorruptionError(
                ResearchRunStoreReason.CONTENT_INVALID
            )
        if not _result_identity_matches(result, run_id=run_id, paper_id=paper_id):
            raise ResearchRunStoreCorruptionError(
                ResearchRunStoreReason.IDENTITY_MISMATCH
            )
        result_checksum = _corrupt_checksum(state.get("result_checksum"))
        if not _constant_time_equal(result_checksum, _state_checksum(result)):
            raise ResearchRunStoreCorruptionError(
                ResearchRunStoreReason.CHECKSUM_INVALID
            )
        checksum = _corrupt_checksum(state.get("checksum"))
        unsigned = {key: state[key] for key in _RECORD_FIELDS - {"checksum"}}
        if not _constant_time_equal(checksum, _state_checksum(unsigned)):
            raise ResearchRunStoreCorruptionError(
                ResearchRunStoreReason.CHECKSUM_INVALID
            )
        return _PersistedRecord(
            run_id=run_id,
            paper_id=paper_id,
            commit_generation=generation,
            committed_at=committed_at,
            result=result,
            result_checksum=result_checksum,
            checksum=checksum,
        )

    def _read_index(self, paper_id: str) -> _PersistedIndex | None:
        path = self._index_path(paper_id)
        _assert_descendant(self._root, path)
        state = _read_json_file(path, max_bytes=_LATEST_INDEX_MAX_BYTES)
        if state is None:
            return None
        if set(state) != _INDEX_FIELDS:
            raise ResearchRunStoreCorruptionError(ResearchRunStoreReason.SCHEMA_INVALID)
        if state.get("schema_version") != RESEARCH_RUN_LATEST_INDEX_SCHEMA_VERSION:
            raise ResearchRunStoreCorruptionError(
                ResearchRunStoreReason.SCHEMA_UNSUPPORTED
            )
        stored_paper_id = _corrupt_identity(state.get("paper_id"))
        run_id = _corrupt_identity(state.get("run_id"))
        if stored_paper_id != paper_id or path.name != _hashed_filename(paper_id):
            raise ResearchRunStoreCorruptionError(
                ResearchRunStoreReason.IDENTITY_MISMATCH
            )
        generation = _corrupt_generation(state.get("commit_generation"))
        committed_at = _corrupt_timestamp(state.get("committed_at"))
        record_checksum = _corrupt_checksum(state.get("record_checksum"))
        checksum = _corrupt_checksum(state.get("checksum"))
        unsigned = {key: state[key] for key in _INDEX_FIELDS - {"checksum"}}
        if not _constant_time_equal(checksum, _state_checksum(unsigned)):
            raise ResearchRunStoreCorruptionError(
                ResearchRunStoreReason.CHECKSUM_INVALID
            )
        return _PersistedIndex(
            paper_id=stored_paper_id,
            run_id=run_id,
            commit_generation=generation,
            committed_at=committed_at,
            record_checksum=record_checksum,
            checksum=checksum,
        )

    def _synchronize_latest_index(
        self,
        paper_id: str,
        *,
        records: list[_PersistedRecord],
        current: _PersistedIndex | None,
    ) -> _PersistedRecord | None:
        matching = [record for record in records if record.paper_id == paper_id]
        if not matching:
            if current is not None:
                raise ResearchRunStoreCorruptionError(
                    ResearchRunStoreReason.IDENTITY_MISMATCH
                )
            return None
        latest = max(matching, key=lambda item: item.commit_key)
        if current is not None and _index_matches_record(current, latest):
            return latest
        self._write_index(latest)
        repaired = self._read_index(paper_id)
        if repaired is None or not _index_matches_record(repaired, latest):
            raise ResearchRunStoreCorruptionError(
                ResearchRunStoreReason.IDENTITY_MISMATCH
            )
        return latest

    def _write_index(self, record: _PersistedRecord) -> None:
        unsigned = {
            "schema_version": RESEARCH_RUN_LATEST_INDEX_SCHEMA_VERSION,
            "paper_id": record.paper_id,
            "run_id": record.run_id,
            "commit_generation": record.commit_generation,
            "committed_at": record.committed_at,
            "record_checksum": record.checksum,
        }
        state = {**unsigned, "checksum": _state_checksum(unsigned)}
        encoded = _encoded_json(
            state,
            max_bytes=_LATEST_INDEX_MAX_BYTES,
            too_large_reason=ResearchRunStoreReason.SERIALIZATION_FAILED,
        )
        _write_atomic(self._index_path(record.paper_id), encoded)

    def _decode_record(self, persisted: _PersistedRecord) -> ResearchRunRecord:
        try:
            result = self._result_decoder(copy.deepcopy(persisted.result))
        except Exception:
            raise ResearchRunStoreCorruptionError(
                ResearchRunStoreReason.CONTENT_INVALID
            ) from None
        try:
            round_trip = _result_projection(result)
        except ResearchRunStoreValidationError:
            raise ResearchRunStoreCorruptionError(
                ResearchRunStoreReason.CONTENT_INVALID
            ) from None
        if (
            round_trip != persisted.result
            or not _constant_time_equal(
                _state_checksum(round_trip),
                persisted.result_checksum,
            )
            or not _result_identity_matches(
                round_trip,
                run_id=persisted.run_id,
                paper_id=persisted.paper_id,
            )
        ):
            raise ResearchRunStoreCorruptionError(
                ResearchRunStoreReason.IDENTITY_MISMATCH
            )
        return ResearchRunRecord(
            run_id=persisted.run_id,
            paper_id=persisted.paper_id,
            result=result,
        )

    def _validate_result_before_save(
        self,
        result: dict[str, Any],
        *,
        run_id: str,
        paper_id: str,
        result_checksum: str,
    ) -> None:
        try:
            decoded = self._result_decoder(copy.deepcopy(result))
        except Exception:
            raise ResearchRunStoreValidationError(
                ResearchRunStoreReason.CONTENT_INVALID
            ) from None
        try:
            round_trip = _result_projection(decoded)
        except ResearchRunStoreValidationError:
            raise ResearchRunStoreValidationError(
                ResearchRunStoreReason.CONTENT_INVALID
            ) from None
        if not _result_identity_matches(
            round_trip,
            run_id=run_id,
            paper_id=paper_id,
        ):
            raise ResearchRunStoreValidationError(
                ResearchRunStoreReason.IDENTITY_MISMATCH
            )
        if round_trip != result or not _constant_time_equal(
            _state_checksum(round_trip),
            result_checksum,
        ):
            raise ResearchRunStoreValidationError(
                ResearchRunStoreReason.CONTENT_INVALID
            )

    def _record_path(self, run_id: str) -> Path:
        path = self._records_root / _hashed_filename(run_id)
        _assert_descendant(self._root, path)
        return path

    def _index_path(self, paper_id: str) -> Path:
        path = self._latest_root / _hashed_filename(paper_id)
        _assert_descendant(self._root, path)
        return path


def _validated_root(value: str | os.PathLike[str]) -> Path:
    try:
        raw = os.fspath(value)
        if not raw or "\x00" in raw:
            raise ValueError
        root = Path(raw).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError):
        raise ResearchRunStoreValidationError(
            ResearchRunStoreReason.INVALID_CONFIGURATION
        ) from None
    try:
        if root.exists() and not root.is_dir():
            raise ResearchRunStoreValidationError(
                ResearchRunStoreReason.INVALID_CONFIGURATION
            )
    except OSError:
        raise ResearchRunStoreValidationError(
            ResearchRunStoreReason.INVALID_CONFIGURATION
        ) from None
    return root


def _validated_decoder(value: Any) -> ResearchResultDecoder:
    if not callable(value):
        raise ResearchRunStoreValidationError(
            ResearchRunStoreReason.INVALID_CONFIGURATION
        )
    return value


def _validated_max_bytes(value: Any) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < _MIN_RECORD_BYTES
        or value > _MAX_RECORD_BYTES
    ):
        raise ResearchRunStoreValidationError(
            ResearchRunStoreReason.INVALID_CONFIGURATION
        )
    return value


def _validated_identity(value: Any) -> str:
    if not _identity_is_valid(value):
        raise ResearchRunStoreValidationError(ResearchRunStoreReason.INVALID_RECORD)
    return value


def _corrupt_identity(value: Any) -> str:
    if not _identity_is_valid(value):
        raise ResearchRunStoreCorruptionError(ResearchRunStoreReason.IDENTITY_MISMATCH)
    return value


def _identity_is_valid(value: Any) -> bool:
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        return False
    try:
        return len(value.encode("utf-8")) <= _MAX_ID_BYTES
    except UnicodeError:
        return False


def _result_projection(value: Any) -> dict[str, Any]:
    try:
        if isinstance(value, Mapping):
            raw = dict(value)
        else:
            to_persistence_dict = getattr(value, "to_persistence_dict", None)
            to_dict = getattr(value, "to_dict", None)
            encoder = to_persistence_dict if callable(to_persistence_dict) else to_dict
            if not callable(encoder):
                raise TypeError
            raw = encoder()
        if not isinstance(raw, Mapping):
            raise TypeError
        normalized = json.loads(
            _canonical_json(dict(raw)),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_strict_json_object,
        )
    except (TypeError, ValueError, UnicodeError, json.JSONDecodeError):
        raise ResearchRunStoreValidationError(
            ResearchRunStoreReason.SERIALIZATION_FAILED
        ) from None
    except Exception:
        raise ResearchRunStoreValidationError(
            ResearchRunStoreReason.SERIALIZATION_FAILED
        ) from None
    if not isinstance(normalized, dict):
        raise ResearchRunStoreValidationError(
            ResearchRunStoreReason.SERIALIZATION_FAILED
        )
    return normalized


def _result_identity_matches(
    result: Mapping[str, Any],
    *,
    run_id: str,
    paper_id: str,
) -> bool:
    if result.get("run_id") != run_id:
        return False
    expected_trace_ref = f"harness-trace://{run_id}"
    trace_ref = result.get("trace_ref")
    if trace_ref is not None and trace_ref != expected_trace_ref:
        return False
    for field in ("trace", "transcript"):
        nested = result.get(field)
        if isinstance(nested, Mapping):
            nested_run_id = nested.get("run_id")
            if nested_run_id is not None and nested_run_id != run_id:
                return False
    for path in _RESULT_PAPER_ID_PATHS:
        value = _nested_value(result, path)
        if value is not None and value != paper_id:
            return False
    return True


def _nested_value(value: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = value
    for part in path:
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _corrupt_generation(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ResearchRunStoreCorruptionError(ResearchRunStoreReason.CONTENT_INVALID)
    return value


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _corrupt_timestamp(value: Any) -> str:
    if not isinstance(value, str):
        raise ResearchRunStoreCorruptionError(ResearchRunStoreReason.CONTENT_INVALID)
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError:
        raise ResearchRunStoreCorruptionError(
            ResearchRunStoreReason.CONTENT_INVALID
        ) from None
    canonical = (
        parsed.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    if value != canonical:
        raise ResearchRunStoreCorruptionError(ResearchRunStoreReason.CONTENT_INVALID)
    return value


def _corrupt_checksum(value: Any) -> str:
    if not isinstance(value, str) or _CHECKSUM.fullmatch(value) is None:
        raise ResearchRunStoreCorruptionError(ResearchRunStoreReason.CHECKSUM_INVALID)
    return value


def _index_matches_record(
    index: _PersistedIndex,
    record: _PersistedRecord,
) -> bool:
    return (
        index.paper_id == record.paper_id
        and index.run_id == record.run_id
        and index.commit_generation == record.commit_generation
        and index.committed_at == record.committed_at
        and _constant_time_equal(index.record_checksum, record.checksum)
    )


def _hashed_filename(identity: str) -> str:
    return f"{sha256(identity.encode('utf-8')).hexdigest()}.json"


def _state_checksum(unsigned: Mapping[str, Any]) -> str:
    digest = sha256(_canonical_json(unsigned).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


def _encoded_json(
    value: Mapping[str, Any],
    *,
    max_bytes: int,
    too_large_reason: ResearchRunStoreReason,
) -> bytes:
    try:
        encoded = (_canonical_json(value) + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise ResearchRunStoreValidationError(
            ResearchRunStoreReason.SERIALIZATION_FAILED
        ) from None
    if len(encoded) > max_bytes:
        raise ResearchRunStoreValidationError(too_large_reason)
    return encoded


def _constant_time_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)


def _run_store_failure_reason(exc: Exception) -> str:
    if isinstance(exc, ResearchRunStoreError):
        return exc.reason_code
    if isinstance(exc, OSError):
        return ResearchRunStoreReason.FILESYSTEM_UNAVAILABLE.value
    if isinstance(exc, (TypeError, ValueError)):
        return ResearchRunStoreReason.INVALID_RECORD.value
    return "other"


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON object key")
        value[key] = item
    return value


def _read_json_file(path: Path, *, max_bytes: int) -> dict[str, Any] | None:
    try:
        inspected = path.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        raise ResearchRunStoreUnavailableError(
            ResearchRunStoreReason.FILESYSTEM_UNAVAILABLE
        ) from None
    if not stat.S_ISREG(inspected.st_mode):
        raise ResearchRunStoreCorruptionError(ResearchRunStoreReason.CONTENT_INVALID)
    try:
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(
                inspected,
                opened,
            ):
                raise ResearchRunStoreCorruptionError(
                    ResearchRunStoreReason.IDENTITY_MISMATCH
                )
            if opened.st_size > max_bytes:
                raise ResearchRunStoreCorruptionError(
                    ResearchRunStoreReason.RECORD_TOO_LARGE
                )
            encoded = handle.read(max_bytes + 1)
    except ResearchRunStoreCorruptionError:
        raise
    except OSError:
        raise ResearchRunStoreUnavailableError(
            ResearchRunStoreReason.FILESYSTEM_UNAVAILABLE
        ) from None
    if len(encoded) > max_bytes:
        raise ResearchRunStoreCorruptionError(ResearchRunStoreReason.RECORD_TOO_LARGE)
    try:
        state = json.loads(
            encoded.decode("utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_strict_json_object,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError):
        raise ResearchRunStoreCorruptionError(
            ResearchRunStoreReason.CONTENT_INVALID
        ) from None
    if not isinstance(state, dict):
        raise ResearchRunStoreCorruptionError(ResearchRunStoreReason.SCHEMA_INVALID)
    return state


def _path_lock(path: Path) -> threading.RLock:
    with _PATH_LOCKS_GUARD:
        lock = _PATH_LOCKS.get(path)
        if lock is None:
            lock = threading.RLock()
            _PATH_LOCKS[path] = lock
        return lock


def _directory_exists(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    except OSError:
        raise ResearchRunStoreUnavailableError(
            ResearchRunStoreReason.FILESYSTEM_UNAVAILABLE
        ) from None
    if not stat.S_ISDIR(mode):
        raise ResearchRunStoreCorruptionError(ResearchRunStoreReason.CONTENT_INVALID)
    return True


def _ensure_directory(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except FileExistsError:
        pass
    except OSError:
        raise ResearchRunStoreUnavailableError(
            ResearchRunStoreReason.FILESYSTEM_UNAVAILABLE
        ) from None
    if not _directory_exists(path):
        raise ResearchRunStoreCorruptionError(ResearchRunStoreReason.CONTENT_INVALID)


def _assert_missing_or_regular_file(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    except OSError:
        raise ResearchRunStoreUnavailableError(
            ResearchRunStoreReason.FILESYSTEM_UNAVAILABLE
        ) from None
    if not stat.S_ISREG(mode):
        raise ResearchRunStoreCorruptionError(ResearchRunStoreReason.CONTENT_INVALID)


def _assert_descendant(root: Path, path: Path) -> None:
    try:
        path.resolve(strict=False).relative_to(root)
    except (OSError, RuntimeError, ValueError):
        raise ResearchRunStoreCorruptionError(
            ResearchRunStoreReason.IDENTITY_MISMATCH
        ) from None


@contextmanager
def _exclusive_file_lock(path: Path) -> Iterator[None]:
    _assert_missing_or_regular_file(path)
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError:
        _assert_missing_or_regular_file(path)
        raise ResearchRunStoreUnavailableError(
            ResearchRunStoreReason.LOCK_UNAVAILABLE
        ) from None

    try:
        opened = os.fstat(descriptor)
        inspected = path.lstat()
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(inspected.st_mode)
            or not os.path.samestat(opened, inspected)
        ):
            raise ResearchRunStoreCorruptionError(
                ResearchRunStoreReason.IDENTITY_MISMATCH
            )
        if os.name == "nt":
            import msvcrt

            if opened.st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX)
        locked = path.lstat()
        if not stat.S_ISREG(locked.st_mode) or not os.path.samestat(opened, locked):
            raise ResearchRunStoreCorruptionError(
                ResearchRunStoreReason.IDENTITY_MISMATCH
            )
    except ResearchRunStoreCorruptionError:
        os.close(descriptor)
        raise
    except (OSError, FileNotFoundError):
        os.close(descriptor)
        raise ResearchRunStoreUnavailableError(
            ResearchRunStoreReason.LOCK_UNAVAILABLE
        ) from None
    except Exception:
        os.close(descriptor)
        raise

    try:
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            os.close(descriptor)


def _write_atomic(path: Path, encoded: bytes) -> None:
    _assert_missing_or_regular_file(path)
    try:
        descriptor, raw_temporary = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
    except OSError:
        raise ResearchRunStoreUnavailableError(
            ResearchRunStoreReason.ATOMIC_COMMIT_FAILED
        ) from None
    temporary = Path(raw_temporary)
    owned: os.stat_result | None = None
    try:
        owned = os.fstat(descriptor)
        if not stat.S_ISREG(owned.st_mode):
            raise ResearchRunStoreCorruptionError(
                ResearchRunStoreReason.CONTENT_INVALID
            )
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        inspected = temporary.lstat()
        if not stat.S_ISREG(inspected.st_mode) or not os.path.samestat(
            owned,
            inspected,
        ):
            raise ResearchRunStoreCorruptionError(
                ResearchRunStoreReason.IDENTITY_MISMATCH
            )
        _replace_with_retry(temporary, path)
        _fsync_directory(path.parent)
    except ResearchRunStoreCorruptionError:
        if owned is not None:
            _cleanup_owned_temp(temporary, owned)
        raise
    except OSError:
        if owned is not None:
            _cleanup_owned_temp(temporary, owned)
        raise ResearchRunStoreUnavailableError(
            ResearchRunStoreReason.ATOMIC_COMMIT_FAILED
        ) from None
    finally:
        if descriptor != -1:
            os.close(descriptor)
    if owned is None:
        raise ResearchRunStoreUnavailableError(
            ResearchRunStoreReason.ATOMIC_COMMIT_FAILED
        )
    _cleanup_owned_temp(temporary, owned)


def _cleanup_owned_temp(path: Path, owned: os.stat_result) -> None:
    try:
        inspected = path.lstat()
    except FileNotFoundError:
        return
    except OSError:
        raise ResearchRunStoreUnavailableError(
            ResearchRunStoreReason.ATOMIC_COMMIT_FAILED
        ) from None
    if not os.path.samestat(owned, inspected):
        raise ResearchRunStoreCorruptionError(ResearchRunStoreReason.IDENTITY_MISMATCH)
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        raise ResearchRunStoreUnavailableError(
            ResearchRunStoreReason.ATOMIC_COMMIT_FAILED
        ) from None


def _replace_with_retry(source: Path, destination: Path) -> None:
    attempts = 8 if os.name == "nt" else 1
    for attempt in range(attempts):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.01 * (attempt + 1))


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "DEFAULT_RESEARCH_RUN_RECORD_MAX_BYTES",
    "FilesystemResearchRunStore",
    "RESEARCH_RUN_LATEST_INDEX_SCHEMA_VERSION",
    "RESEARCH_RUN_RECORD_SCHEMA_VERSION",
    "ResearchResultDecoder",
]
