from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from framework.shared.time import ensure_utc, format_datetime, parse_datetime
from framework.workers.scheduler.schedule import ScheduleSpec


class ScheduleNotFoundError(KeyError):
    """Raised when a schedule id is not present in a schedule store."""


class ScheduleStore(Protocol):
    def list_schedules(self, *, enabled_only: bool = False) -> list["ScheduleRecord"]: ...

    def get_schedule(self, schedule_id: str) -> "ScheduleRecord": ...

    def upsert_schedule(self, record: "ScheduleRecord") -> "ScheduleRecord": ...

    def delete_schedule(self, schedule_id: str) -> bool: ...

    def update_run_state(
        self,
        schedule_id: str,
        *,
        last_run_at: datetime | None,
        next_run_at: datetime | None,
        last_misfire_reason: str | None = None,
        last_evaluation_at: datetime | None = None,
    ) -> "ScheduleRecord": ...


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
    ) -> "ScheduleRecord":
        return ScheduleRecord(
            spec=self.spec,
            last_run_at=ensure_utc(last_run_at) if last_run_at is not None else None,
            next_run_at=ensure_utc(next_run_at) if next_run_at is not None else None,
            last_misfire_reason=last_misfire_reason,
            last_evaluation_at=ensure_utc(last_evaluation_at) if last_evaluation_at is not None else None,
            created_at=self.created_at,
            updated_at=ensure_utc(updated_at) if updated_at is not None else datetime.now(UTC),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec": self.spec.to_dict(),
            "last_run_at": format_datetime(self.last_run_at),
            "next_run_at": format_datetime(self.next_run_at),
            "last_misfire_reason": self.last_misfire_reason,
            "last_evaluation_at": format_datetime(self.last_evaluation_at),
            "created_at": format_datetime(self.created_at),
            "updated_at": format_datetime(self.updated_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScheduleRecord":
        return cls(
            spec=ScheduleSpec.from_dict(dict(data["spec"])),
            last_run_at=parse_datetime(data.get("last_run_at")),
            next_run_at=parse_datetime(data.get("next_run_at")),
            last_misfire_reason=data.get("last_misfire_reason"),
            last_evaluation_at=parse_datetime(data.get("last_evaluation_at")),
            created_at=parse_datetime(data.get("created_at")) or datetime.now(UTC),
            updated_at=parse_datetime(data.get("updated_at")) or datetime.now(UTC),
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
