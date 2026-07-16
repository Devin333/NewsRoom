from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from framework.events.migration_backfill import (
    MigrationBackfillReport,
    MigrationBackfillStatus,
    MigrationResumeError,
    MigrationShadowReport,
)
from framework.shared.json import stable_json_dumps


_PATH_LOCKS: dict[Path, threading.RLock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


class MigrationReportStoreError(RuntimeError):
    """A migration report could not be read or committed durably."""


class JsonMigrationBackfillReportStore:
    """One checksum-verified, monotonically advancing backfill report file."""

    def __init__(self, path: str | Path) -> None:
        self.path = _report_path(path)

    def load(self, report_id: str) -> MigrationBackfillReport | None:
        expected_id = _required_text(report_id, "report_id")
        with _locked_report(self.path):
            report = _read_backfill_report(self.path)
        if report is not None and report.report_id != expected_id:
            raise MigrationResumeError("migration report identity does not match")
        return report

    def save(self, report: MigrationBackfillReport) -> None:
        if not isinstance(report, MigrationBackfillReport):
            raise TypeError("report must be a MigrationBackfillReport")
        with _locked_report(self.path):
            current = _read_backfill_report(self.path)
            selected = _select_monotonic_report(current, report)
            if current is not None and selected.report_checksum == current.report_checksum:
                return
            _write_json_atomic(self.path, selected.to_dict())


def write_migration_shadow_report(
    path: str | Path,
    report: MigrationShadowReport,
) -> Path:
    if not isinstance(report, MigrationShadowReport):
        raise TypeError("report must be a MigrationShadowReport")
    resolved = _report_path(path)
    with _locked_report(resolved):
        current = _read_shadow_report(resolved)
        if current is not None:
            if current.backfill_report_id != report.backfill_report_id:
                raise MigrationReportStoreError(
                    "shadow report identity does not match existing report"
                )
            if current.report_checksum == report.report_checksum:
                return resolved
        _write_json_atomic(resolved, report.to_dict())
    return resolved


def read_migration_shadow_report(path: str | Path) -> MigrationShadowReport | None:
    resolved = _report_path(path)
    with _locked_report(resolved):
        return _read_shadow_report(resolved)


def _select_monotonic_report(
    current: MigrationBackfillReport | None,
    incoming: MigrationBackfillReport,
) -> MigrationBackfillReport:
    if current is None:
        return incoming
    if (
        current.report_id != incoming.report_id
        or current.source_fingerprint != incoming.source_fingerprint
        or current.records_fingerprint != incoming.records_fingerprint
        or current.started_at != incoming.started_at
    ):
        raise MigrationResumeError("migration report scope cannot change")
    current_entries = current.entries
    incoming_entries = incoming.entries
    shared = min(len(current_entries), len(incoming_entries))
    if current_entries[:shared] != incoming_entries[:shared]:
        raise MigrationResumeError("migration report progress diverged")
    if len(incoming_entries) < len(current_entries):
        return current
    if current.status is not MigrationBackfillStatus.RUNNING:
        if incoming.report_checksum != current.report_checksum:
            raise MigrationResumeError("terminal migration report cannot change")
        return current
    if incoming.updated_at < current.updated_at:
        raise MigrationResumeError("migration report update time moved backward")
    return incoming


def _read_backfill_report(path: Path) -> MigrationBackfillReport | None:
    payload = _read_json_object(path)
    if payload is None:
        return None
    try:
        return MigrationBackfillReport.from_dict(payload)
    except (KeyError, TypeError, ValueError) as error:
        raise MigrationReportStoreError("migration backfill report is invalid") from error


def _read_shadow_report(path: Path) -> MigrationShadowReport | None:
    payload = _read_json_object(path)
    if payload is None:
        return None
    try:
        return MigrationShadowReport.from_dict(payload)
    except (KeyError, TypeError, ValueError) as error:
        raise MigrationReportStoreError("migration shadow report is invalid") from error


def _read_json_object(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MigrationReportStoreError("migration report could not be read") from error
    if not isinstance(payload, Mapping):
        raise MigrationReportStoreError("migration report root must be an object")
    return dict(payload)


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    encoded = (stable_json_dumps(dict(payload)) + "\n").encode("utf-8")
    try:
        with temporary.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(temporary, path)
        _fsync_directory(path.parent)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


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


@contextmanager
def _locked_report(path: Path) -> Iterator[None]:
    lock = _path_lock(path)
    with lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = path.with_name(f".{path.name}.lock")
        with lock_path.open("a+b") as handle:
            _lock_handle(handle)
            try:
                yield
            finally:
                _unlock_handle(handle)


def _path_lock(path: Path) -> threading.RLock:
    with _PATH_LOCKS_GUARD:
        lock = _PATH_LOCKS.get(path)
        if lock is None:
            lock = threading.RLock()
            _PATH_LOCKS[path] = lock
        return lock


def _lock_handle(handle: Any) -> None:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
        os.fsync(handle.fileno())
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock_handle(handle: Any) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _report_path(path: str | Path) -> Path:
    resolved = Path(path).expanduser().resolve()
    if resolved.suffix.lower() != ".json":
        raise ValueError("migration report path must use a .json extension")
    return resolved


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


__all__ = [
    "JsonMigrationBackfillReportStore",
    "MigrationReportStoreError",
    "read_migration_shadow_report",
    "write_migration_shadow_report",
]
