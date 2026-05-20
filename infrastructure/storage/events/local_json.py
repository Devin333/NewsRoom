from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

from infrastructure.storage.events.models import EventRecord
from infrastructure.storage.security import StorageRedactor


class LocalJsonEventStore:
    def __init__(
        self,
        root: str | Path = ".newsroom/runs/_records/events",
        *,
        redactor: StorageRedactor | None = None,
    ) -> None:
        self.root = Path(root)
        self.redactor = redactor or StorageRedactor()

    def append_event(self, event: EventRecord) -> int:
        _validate_event(event)
        event = self._redacted_event(event)
        path = self._events_path(event.run_id)
        offset = _line_count(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        return offset

    def list_by_run(self, run_id: str, limit: int | None = None) -> list[EventRecord]:
        _validate_id(run_id, "run_id")
        if limit is not None and limit <= 0:
            raise ValueError("limit must be greater than zero")
        path = self._events_path(run_id)
        if not path.exists():
            return []
        events = _read_events(path)
        if limit is not None:
            return events[:limit]
        return events

    def list_by_step(self, run_id: str, step_id: str) -> list[EventRecord]:
        _validate_id(step_id, "step_id")
        return [event for event in self.list_by_run(run_id) if event.step_id == step_id]

    def filter_by_type(
        self,
        run_id: str,
        event_type: str,
        *,
        limit: int | None = None,
    ) -> list[EventRecord]:
        if not event_type:
            raise ValueError("event_type is required")
        if limit is not None and limit <= 0:
            raise ValueError("limit must be greater than zero")
        events = [event for event in self.list_by_run(run_id) if event.event_type == event_type]
        if limit is not None:
            return events[:limit]
        return events

    async def stream_from_offset(self, run_id: str, offset: int) -> AsyncIterator[EventRecord]:
        _validate_id(run_id, "run_id")
        if offset < 0:
            raise ValueError("offset must be greater than or equal to zero")
        for index, event in enumerate(self.list_by_run(run_id)):
            if index >= offset:
                yield event

    def _events_path(self, run_id: str) -> Path:
        _validate_id(run_id, "run_id")
        return self.root / f"{run_id}.jsonl"

    def _redacted_event(self, event: EventRecord) -> EventRecord:
        payload_redaction = self.redactor.redact(
            event.payload,
            run_id=event.run_id,
            artifact_id=event.event_id,
        )
        metadata_redaction = self.redactor.redact(
            event.metadata,
            run_id=event.run_id,
            artifact_id=f"{event.event_id}:metadata",
        )
        metadata = dict(metadata_redaction.value)
        reports = []
        if payload_redaction.redacted:
            reports.append(payload_redaction.report.to_dict())
        if metadata_redaction.redacted:
            reports.append(metadata_redaction.report.to_dict())
        if reports:
            metadata["redaction_reports"] = reports
        return EventRecord(
            event_id=event.event_id,
            run_id=event.run_id,
            event_type=event.event_type,
            timestamp=event.timestamp,
            workflow_id=event.workflow_id,
            step_id=event.step_id,
            task_id=event.task_id,
            agent_id=event.agent_id,
            tool_call_id=event.tool_call_id,
            request_id=event.request_id,
            payload=dict(payload_redaction.value),
            severity=event.severity,
            trace_id=event.trace_id,
            redacted=True,
            metadata=metadata,
        )


def _read_events(path: Path) -> list[EventRecord]:
    events = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            events.append(EventRecord.from_dict(json.loads(stripped)))
    return events


def _line_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def _validate_event(event: EventRecord) -> None:
    _validate_id(event.run_id, "run_id")
    if not event.event_id:
        raise ValueError("event_id is required")
    if not event.event_type:
        raise ValueError("event_type is required")
    if event.step_id is not None:
        _validate_id(event.step_id, "step_id")


def _validate_id(value: str, label: str) -> None:
    if not value:
        raise ValueError(f"{label} is required")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 1:
        raise ValueError(f"invalid {label}: {value}")
