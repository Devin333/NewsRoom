from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from core.framework.workers.schedule_store import (
    ScheduleNotFoundError,
    ScheduleRecord,
)


SCHEDULE_STORE_SCHEMA_VERSION = "schedule_store.v1"


class LocalJsonScheduleStore:
    def __init__(self, path: str | Path = ".newsroom/schedules/schedules.json") -> None:
        self.path = Path(path)

    def list_schedules(self, *, enabled_only: bool = False) -> list[ScheduleRecord]:
        records = sorted(self._read_records().values(), key=lambda record: record.schedule_id)
        if enabled_only:
            return [record for record in records if record.enabled]
        return records

    def get_schedule(self, schedule_id: str) -> ScheduleRecord:
        records = self._read_records()
        try:
            return records[schedule_id]
        except KeyError as exc:
            raise ScheduleNotFoundError(schedule_id) from exc

    def upsert_schedule(self, record: ScheduleRecord) -> ScheduleRecord:
        records = self._read_records()
        records[record.schedule_id] = record
        self._write_records(records)
        return record

    def delete_schedule(self, schedule_id: str) -> bool:
        records = self._read_records()
        if schedule_id not in records:
            return False
        records.pop(schedule_id)
        self._write_records(records)
        return True

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
        )
        self.upsert_schedule(updated)
        return updated

    def _read_records(self) -> dict[str, ScheduleRecord]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        schedules = payload.get("schedules", [])
        records = [ScheduleRecord.from_dict(item) for item in schedules]
        return {record.schedule_id: record for record in records}

    def _write_records(self, records: dict[str, ScheduleRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SCHEDULE_STORE_SCHEMA_VERSION,
            "schedules": [
                record.to_dict()
                for record in sorted(records.values(), key=lambda item: item.schedule_id)
            ],
        }
        temp_path = self.path.with_name(f"{self.path.name}.tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        temp_path.replace(self.path)
