from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from core.framework.workers.scheduler import ScheduleSpec


class ScheduleNotFoundError(KeyError):
    """Raised when a schedule id is not present in a schedule store."""


class ScheduleStore(Protocol):
    def list_schedules(self, *, enabled_only: bool = False) -> list[ScheduleRecord]: ...

    def get_schedule(self, schedule_id: str) -> ScheduleRecord: ...

    def upsert_schedule(self, record: ScheduleRecord) -> ScheduleRecord: ...

    def delete_schedule(self, schedule_id: str) -> bool: ...

    def update_run_state(
        self,
        schedule_id: str,
        *,
        last_run_at: datetime | None,
        next_run_at: datetime | None,
        last_misfire_reason: str | None = None,
        last_evaluation_at: datetime | None = None,
    ) -> ScheduleRecord: ...


@dataclass(frozen=True)
class ScheduleRecord:
    spec: ScheduleSpec
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    last_misfire_reason: str | None = None
    last_evaluation_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def schedule_id(self) -> str:
        return self.spec.schedule_id

    @property
    def enabled(self) -> bool:
        return self.spec.enabled

    def with_state(
        self,
        *,
        last_run_at: datetime | None,
        next_run_at: datetime | None,
        updated_at: datetime | None = None,
        last_misfire_reason: str | None = None,
        last_evaluation_at: datetime | None = None,
    ) -> ScheduleRecord:
        return ScheduleRecord(
            spec=self.spec,
            last_run_at=_normalize_datetime(last_run_at),
            next_run_at=_normalize_datetime(next_run_at),
            last_misfire_reason=last_misfire_reason,
            last_evaluation_at=_normalize_datetime(last_evaluation_at),
            created_at=self.created_at,
            updated_at=_normalize_datetime(updated_at) or datetime.now(UTC),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec": self.spec.to_dict(),
            "last_run_at": _format_datetime(self.last_run_at),
            "next_run_at": _format_datetime(self.next_run_at),
            "last_misfire_reason": self.last_misfire_reason,
            "last_evaluation_at": _format_datetime(self.last_evaluation_at),
            "created_at": _format_datetime(self.created_at),
            "updated_at": _format_datetime(self.updated_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScheduleRecord:
        return cls(
            spec=ScheduleSpec.from_dict(dict(data["spec"])),
            last_run_at=_parse_optional_datetime(data.get("last_run_at")),
            next_run_at=_parse_optional_datetime(data.get("next_run_at")),
            last_misfire_reason=data.get("last_misfire_reason"),
            last_evaluation_at=_parse_optional_datetime(data.get("last_evaluation_at")),
            created_at=_parse_optional_datetime(data.get("created_at")) or datetime.now(UTC),
            updated_at=_parse_optional_datetime(data.get("updated_at")) or datetime.now(UTC),
        )


class InMemoryScheduleStore:
    def __init__(
        self,
        records: list[ScheduleRecord] | None = None,
        *,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._records = {record.schedule_id: record for record in records or []}
        self.now_fn = now_fn or (lambda: datetime.now(UTC))

    def list_schedules(self, *, enabled_only: bool = False) -> list[ScheduleRecord]:
        records = sorted(self._records.values(), key=lambda record: record.schedule_id)
        if enabled_only:
            return [record for record in records if record.enabled]
        return records

    def get_schedule(self, schedule_id: str) -> ScheduleRecord:
        try:
            return self._records[schedule_id]
        except KeyError as exc:
            raise ScheduleNotFoundError(schedule_id) from exc

    def upsert_schedule(self, record: ScheduleRecord) -> ScheduleRecord:
        self._records[record.schedule_id] = record
        return record

    def delete_schedule(self, schedule_id: str) -> bool:
        return self._records.pop(schedule_id, None) is not None

    def update_run_state(
        self,
        schedule_id: str,
        *,
        last_run_at: datetime | None,
        next_run_at: datetime | None,
        last_misfire_reason: str | None = None,
        last_evaluation_at: datetime | None = None,
    ) -> ScheduleRecord:
        record = self.get_schedule(schedule_id)
        updated = record.with_state(
            last_run_at=last_run_at,
            next_run_at=next_run_at,
            last_misfire_reason=last_misfire_reason,
            last_evaluation_at=last_evaluation_at,
            updated_at=self.now_fn(),
        )
        self.upsert_schedule(updated)
        return updated


def _format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _normalize_datetime(value).isoformat().replace("+00:00", "Z")


def _parse_optional_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return _normalize_datetime(value)
    if isinstance(value, str):
        return _normalize_datetime(datetime.fromisoformat(value.replace("Z", "+00:00")))
    raise TypeError(f"unsupported datetime value: {value!r}")


def _normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
