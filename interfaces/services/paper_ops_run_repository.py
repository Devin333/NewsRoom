from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from interfaces.services.json_file_store import locked_json_file, read_json_object, read_json_object_unlocked, write_json_object_unlocked


PAPERS_OPS_STATE_DIR_ENV = "NEWSROOM_PAPERS_OPS_STATE_DIR"
PAPERS_INGEST_STATE_DIR_ENV = "NEWSROOM_PAPERS_INGEST_STATE_DIR"
PAPERS_OPS_ACTIVE_TIMEOUT_SECONDS_ENV = "NEWSROOM_PAPERS_OPS_ACTIVE_TIMEOUT_SECONDS"
DEFAULT_ACTIVE_TIMEOUT_SECONDS = 24 * 60 * 60
ACTIVE_STATUSES = {"queued", "running"}
TERMINAL_STATUSES = {"succeeded", "failed", "partial_failed", "stale_failed"}


class PaperOpsRunRepository:
    def __init__(
        self,
        state_dir: str | Path | None = None,
        *,
        active_timeout_seconds: int | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.state_dir = _state_dir(state_dir)
        self.runs_path = self.state_dir / "ops-runs.json"
        self.active_timeout_seconds = _active_timeout_seconds(active_timeout_seconds)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def record_run(self, run: Mapping[str, Any]) -> None:
        with locked_json_file(self.runs_path) as path:
            payload = read_json_object_unlocked(path, default={"runs": []}, strict=True)
            runs = [dict(item) for item in _sequence(payload.get("runs")) if isinstance(item, Mapping)]
            now = _aware_utc(self.clock())
            next_run = self._with_lease(dict(run), now=now)
            run_id = str(run.get("runId") or "")
            existing = next((item for item in runs if str(item.get("runId") or "") == run_id), {})
            merged = {**dict(existing), **next_run}
            if existing.get("startedAt") and run.get("status") in {"running", *TERMINAL_STATUSES}:
                merged["startedAt"] = existing["startedAt"]
            if str(merged.get("status") or "") not in ACTIVE_STATUSES:
                merged.pop("leaseExpiresAt", None)
            runs = [merged, *[item for item in runs if str(item.get("runId") or "") != run_id]][:200]
            write_json_object_unlocked(path, {"runs": runs})

    def try_enqueue_run(self, run: Mapping[str, Any]) -> tuple[bool, Mapping[str, Any]]:
        with locked_json_file(self.runs_path) as path:
            payload = read_json_object_unlocked(path, default={"runs": []}, strict=True)
            runs = [dict(item) for item in _sequence(payload.get("runs")) if isinstance(item, Mapping)]
            now = _aware_utc(self.clock())
            runs = [self._stale_failed_run(item, now=now) if self._is_stale_active_run(item, now=now) else item for item in runs]
            run_id = str(run.get("runId") or "")
            operation_key = str(run.get("operationKey") or "")
            for existing in runs:
                if str(existing.get("status") or "") not in ACTIVE_STATUSES:
                    continue
                if run_id and str(existing.get("runId") or "") == run_id:
                    return False, dict(existing)
                if operation_key and str(existing.get("operationKey") or "") == operation_key:
                    return False, dict(existing)
            next_run = self._with_lease(dict(run), now=now)
            runs = [next_run, *[item for item in runs if str(item.get("runId") or "") != run_id]][:200]
            write_json_object_unlocked(path, {"runs": runs})
            return True, next_run

    def list_runs(self, *, limit: int = 20) -> list[Mapping[str, Any]]:
        payload = read_json_object(self.runs_path, default={"runs": []}, strict=True)
        return [dict(item) for item in _sequence(payload.get("runs")) if isinstance(item, Mapping)][:limit]

    def _with_lease(self, run: dict[str, Any], *, now: datetime) -> dict[str, Any]:
        status = str(run.get("status") or "")
        if status not in ACTIVE_STATUSES:
            return run
        run.setdefault("updatedAt", _iso(now))
        run.setdefault("startedAt", _iso(now))
        run["leaseExpiresAt"] = _iso(now + timedelta(seconds=self.active_timeout_seconds))
        return run

    def _is_stale_active_run(self, run: Mapping[str, Any], *, now: datetime) -> bool:
        if str(run.get("status") or "") not in ACTIVE_STATUSES:
            return False
        lease_expires_at = _parse_iso_datetime(run.get("leaseExpiresAt"))
        if lease_expires_at is not None:
            return lease_expires_at <= now
        updated_at = _parse_iso_datetime(run.get("updatedAt") or run.get("startedAt"))
        if updated_at is None:
            return True
        return updated_at + timedelta(seconds=self.active_timeout_seconds) <= now

    def _stale_failed_run(self, run: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
        payload = dict(run)
        payload.update(
            {
                "status": "stale_failed",
                "updatedAt": _iso(now),
                "finishedAt": _iso(now),
                "errorCode": "local_ops_run_stale",
                "errorMessage": "local background run did not finish before its active lease expired",
                "retryable": True,
                "stale": True,
            }
        )
        payload.pop("leaseExpiresAt", None)
        return payload


def new_ops_run(
    *,
    run_id: str,
    task_type: str,
    status: str,
    mode: str = "local_background",
    paper_id: str | None = None,
    operation_key: str | None = None,
    error: Exception | None = None,
) -> dict[str, Any]:
    now = _iso_now()
    payload: dict[str, Any] = {
        "runId": run_id,
        "taskType": task_type,
        "status": status,
        "mode": mode,
        "updatedAt": now,
    }
    if status in {"queued", "running"}:
        payload["startedAt"] = now
    if status in {"succeeded", "failed", "partial_failed"}:
        payload["finishedAt"] = now
    if paper_id:
        payload["paperId"] = paper_id
    if operation_key:
        payload["operationKey"] = operation_key
    if error is not None:
        payload["errorCode"] = type(error).__name__
        payload["errorMessage"] = str(error)
        payload["retryable"] = True
    return payload


def _state_dir(configured_path: str | Path | None) -> Path:
    if configured_path is not None:
        return Path(configured_path).expanduser().resolve()
    env_path = os.environ.get(PAPERS_OPS_STATE_DIR_ENV) or os.environ.get(PAPERS_INGEST_STATE_DIR_ENV)
    if env_path:
        return Path(env_path).expanduser().resolve()
    return _project_root() / ".newsroom" / "papers" / "ops"


def _active_timeout_seconds(configured: int | None) -> int:
    value = configured
    if value is None:
        raw = os.environ.get(PAPERS_OPS_ACTIVE_TIMEOUT_SECONDS_ENV)
        if raw:
            try:
                value = int(raw)
            except ValueError:
                value = None
    if value is None:
        value = DEFAULT_ACTIVE_TIMEOUT_SECONDS
    return max(60, int(value))


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []


def _iso_now() -> str:
    return _iso(datetime.now(timezone.utc))


def _iso(value: datetime) -> str:
    return _aware_utc(value).isoformat().replace("+00:00", "Z")


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _aware_utc(parsed)
