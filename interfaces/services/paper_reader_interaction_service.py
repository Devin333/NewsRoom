from __future__ import annotations

import os
import secrets
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from pathlib import Path
from typing import Any, Literal, Protocol

from framework.events.event import Event
from interfaces.services.json_file_store import locked_json_file, read_json_object_unlocked, write_json_object_unlocked


DEFAULT_PAPER_READER_INTERACTIONS_PATH = ".newsroom/papers/reader-interactions.json"
MAX_SELECTED_TEXT_LENGTH = 8000
MAX_SURROUNDING_TEXT_LENGTH = 16000
MAX_NOTE_TEXT_LENGTH = 12000
MAX_QUESTION_LENGTH = 2000
MAX_PAYLOAD_TEXT_LENGTH = 20000

ReaderTargetType = Literal["text_selection", "paragraph", "figure", "table", "equation"]
ReaderEventType = Literal[
    "selection_created",
    "selection_discarded",
    "selection_updated",
    "note_updated",
    "explanation_generated",
    "example_generated",
    "confusion_marked",
    "confusion_unmarked",
    "reader_settings_changed",
    "drawer_resized",
    "toc_navigated",
    "reader_progress_sampled",
    "figure_explanation_requested",
    "figure_explanation_generated",
    "table_explanation_requested",
    "table_explanation_generated",
]

VALID_TARGET_TYPES = {"text_selection", "paragraph", "figure", "table", "equation"}
VALID_EVENT_TYPES = {
    "selection_created",
    "selection_discarded",
    "selection_updated",
    "note_updated",
    "explanation_generated",
    "example_generated",
    "confusion_marked",
    "confusion_unmarked",
    "reader_settings_changed",
    "drawer_resized",
    "toc_navigated",
    "reader_progress_sampled",
    "figure_explanation_requested",
    "figure_explanation_generated",
    "table_explanation_requested",
    "table_explanation_generated",
}

SELECTION_EVENT_TYPES = {
    "selection_created",
    "selection_discarded",
    "selection_updated",
    "note_updated",
    "explanation_generated",
    "example_generated",
    "confusion_marked",
    "confusion_unmarked",
    "figure_explanation_requested",
    "figure_explanation_generated",
    "table_explanation_requested",
    "table_explanation_generated",
}

HIGH_VALUE_EVENT_TYPES = {
    "note_updated",
    "explanation_generated",
    "example_generated",
    "confusion_marked",
    "confusion_unmarked",
    "reader_settings_changed",
    "figure_explanation_requested",
    "figure_explanation_generated",
    "table_explanation_requested",
    "table_explanation_generated",
}


class ReaderSelectionNotFoundError(Exception):
    """Raised when a reader selection is missing or owned by another user."""


@dataclass(frozen=True)
class ReaderBlockTarget:
    targetType: ReaderTargetType
    blockId: str | None = None
    sectionId: str | None = None
    paragraphId: str | None = None
    pageNumber: int | None = None
    sourceBox: dict[str, float] | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"targetType": self.targetType}
        for key, value in (
            ("blockId", self.blockId),
            ("sectionId", self.sectionId),
            ("paragraphId", self.paragraphId),
            ("pageNumber", self.pageNumber),
            ("sourceBox", self.sourceBox),
            ("metadata", self.metadata),
        ):
            if value not in (None, "", {}, []):
                payload[key] = value
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> "ReaderBlockTarget | None":
        if payload is None:
            return None
        if not isinstance(payload, Mapping):
            raise ValueError("target must be an object")
        target_type = _target_type(payload.get("targetType") or payload.get("type"))
        return cls(
            targetType=target_type,
            blockId=_optional_text(payload.get("blockId")),
            sectionId=_optional_text(payload.get("sectionId")),
            paragraphId=_optional_text(payload.get("paragraphId")),
            pageNumber=_optional_positive_int(payload.get("pageNumber"), field_name="target.pageNumber"),
            sourceBox=_source_box(payload.get("sourceBox")),
            metadata=_safe_payload_map(payload.get("metadata")),
        )


@dataclass(frozen=True)
class ReaderEvent:
    eventId: str
    type: ReaderEventType
    userId: str
    paperId: str
    selectionId: str | None = None
    target: ReaderBlockTarget | None = None
    sectionId: str | None = None
    paragraphId: str | None = None
    selectedText: str | None = None
    surroundingText: str | None = None
    payload: dict[str, Any] | None = None
    createdAt: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        created_at = self.createdAt or datetime.now(UTC)
        payload: dict[str, Any] = {
            "eventId": self.eventId,
            "type": self.type,
            "eventType": self.type,
            "userId": self.userId,
            "paperId": self.paperId,
            "createdAt": _format_datetime(created_at),
        }
        for key, value in (
            ("selectionId", self.selectionId),
            ("sectionId", self.sectionId),
            ("paragraphId", self.paragraphId),
            ("selectedText", self.selectedText),
            ("surroundingText", self.surroundingText),
            ("payload", self.payload),
        ):
            if value not in (None, "", {}, []):
                payload[key] = value
        if self.target is not None:
            payload["target"] = self.target.to_dict()
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ReaderEvent":
        return cls(
            eventId=str(payload["eventId"]),
            type=_reader_event_type(payload.get("type") or payload.get("eventType")),
            userId=str(payload["userId"]),
            paperId=str(payload["paperId"]),
            selectionId=_optional_text(payload.get("selectionId")),
            target=ReaderBlockTarget.from_dict(payload.get("target") if isinstance(payload.get("target"), Mapping) else None),
            sectionId=_optional_text(payload.get("sectionId")),
            paragraphId=_optional_text(payload.get("paragraphId")),
            selectedText=_optional_limited_text(payload.get("selectedText"), max_length=MAX_SELECTED_TEXT_LENGTH, field_name="selectedText"),
            surroundingText=_optional_limited_text(payload.get("surroundingText"), max_length=MAX_SURROUNDING_TEXT_LENGTH, field_name="surroundingText"),
            payload=_safe_payload_map(payload.get("payload")),
            createdAt=_parse_optional_datetime(payload.get("createdAt")),
        )


@dataclass(frozen=True)
class ReaderSelection:
    selectionId: str
    userId: str
    paperId: str
    target: ReaderBlockTarget
    sectionId: str | None = None
    sectionTitle: str | None = None
    paragraphId: str | None = None
    selectedText: str = ""
    surroundingText: str = ""
    noteText: str | None = None
    explainQuestion: str | None = None
    exampleQuestion: str | None = None
    explained: bool = False
    exampled: bool = False
    confused: bool = False
    createdAt: datetime | None = None
    updatedAt: datetime | None = None

    @property
    def has_material(self) -> bool:
        return bool(self.noteText or self.explained or self.exampled or self.confused)

    @property
    def status(self) -> str:
        if self.confused:
            return "confused"
        if self.explained:
            return "explained"
        if self.exampled:
            return "exampled"
        if self.noteText:
            return "has_note"
        return "temp"

    def to_dict(self) -> dict[str, Any]:
        created_at = self.createdAt or datetime.now(UTC)
        updated_at = self.updatedAt or created_at
        payload: dict[str, Any] = {
            "selectionId": self.selectionId,
            "id": self.selectionId,
            "userId": self.userId,
            "paperId": self.paperId,
            "target": self.target.to_dict(),
            "selectedText": self.selectedText,
            "surroundingText": self.surroundingText,
            "explained": self.explained,
            "exampled": self.exampled,
            "confused": self.confused,
            "status": self.status,
            "createdAt": _format_datetime(created_at),
            "updatedAt": _format_datetime(updated_at),
        }
        for key, value in (
            ("sectionId", self.sectionId),
            ("sectionTitle", self.sectionTitle),
            ("paragraphId", self.paragraphId),
            ("noteText", self.noteText),
            ("explainQuestion", self.explainQuestion),
            ("exampleQuestion", self.exampleQuestion),
        ):
            if value not in (None, ""):
                payload[key] = value
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ReaderSelection":
        target = ReaderBlockTarget.from_dict(payload.get("target") if isinstance(payload.get("target"), Mapping) else None)
        if target is None:
            target = ReaderBlockTarget(
                targetType="text_selection",
                sectionId=_optional_text(payload.get("sectionId")),
                paragraphId=_optional_text(payload.get("paragraphId")),
            )
        selection_id = _optional_text(payload.get("selectionId") or payload.get("id"))
        if not selection_id:
            raise ValueError("selectionId is required")
        return cls(
            selectionId=selection_id,
            userId=str(payload["userId"]),
            paperId=str(payload["paperId"]),
            target=target,
            sectionId=_optional_text(payload.get("sectionId")),
            sectionTitle=_optional_limited_text(payload.get("sectionTitle"), max_length=200, field_name="sectionTitle"),
            paragraphId=_optional_text(payload.get("paragraphId")),
            selectedText=_optional_limited_text(payload.get("selectedText"), max_length=MAX_SELECTED_TEXT_LENGTH, field_name="selectedText") or "",
            surroundingText=_optional_limited_text(payload.get("surroundingText"), max_length=MAX_SURROUNDING_TEXT_LENGTH, field_name="surroundingText") or "",
            noteText=_optional_limited_text(payload.get("noteText"), max_length=MAX_NOTE_TEXT_LENGTH, field_name="noteText"),
            explainQuestion=_optional_limited_text(payload.get("explainQuestion"), max_length=MAX_QUESTION_LENGTH, field_name="explainQuestion"),
            exampleQuestion=_optional_limited_text(payload.get("exampleQuestion"), max_length=MAX_QUESTION_LENGTH, field_name="exampleQuestion"),
            explained=bool(payload.get("explained", False)),
            exampled=bool(payload.get("exampled", False)),
            confused=bool(payload.get("confused", False)),
            createdAt=_parse_optional_datetime(payload.get("createdAt")),
            updatedAt=_parse_optional_datetime(payload.get("updatedAt")),
        )


@dataclass(frozen=True)
class ReaderMaterialSummary:
    paperId: str
    userId: str
    selections: list[ReaderSelection]
    events: list[ReaderEvent]

    def to_dict(self) -> dict[str, Any]:
        material_selections = [selection for selection in self.selections if selection.has_material]
        return {
            "paperId": self.paperId,
            "userId": self.userId,
            "selections": [selection.to_dict() for selection in material_selections],
            "events": [event.to_dict() for event in self.events],
            "stats": {
                "noteCount": sum(1 for selection in material_selections if selection.noteText),
                "explainedCount": sum(1 for selection in material_selections if selection.explained),
                "exampledCount": sum(1 for selection in material_selections if selection.exampled),
                "confusedCount": sum(1 for selection in material_selections if selection.confused),
                "materialCount": len(material_selections),
            },
        }


@dataclass(frozen=True)
class ReaderLearningSignal:
    signalId: str
    signalType: str
    userId: str | None
    paperId: str
    eventId: str
    selectionId: str | None = None
    target: dict[str, Any] | None = None
    content: str | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "signalId": self.signalId,
            "signalType": self.signalType,
            "userId": self.userId,
            "paperId": self.paperId,
            "eventId": self.eventId,
            "selectionId": self.selectionId,
            "target": dict(self.target or {}),
            "content": self.content,
            "metadata": dict(self.metadata or {}),
        }


@dataclass(frozen=True)
class ReaderEventRecordResult:
    event: ReaderEvent
    selection: ReaderSelection | None
    materialSummary: ReaderMaterialSummary

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event.to_dict(),
            "selection": self.selection.to_dict() if self.selection else None,
            "materials": self.materialSummary.to_dict(),
        }


class ReaderEventRepository(Protocol):
    def append_event(self, event: ReaderEvent) -> ReaderEvent: ...
    def list_events(self, user_id: str, paper_id: str, *, limit: int | None = None) -> list[ReaderEvent]: ...
    def list_unprocessed_events(self, *, limit: int = 100, user_id: str | None = None, paper_id: str | None = None) -> list[ReaderEvent]: ...
    def mark_events_processed(self, event_ids: Sequence[str]) -> None: ...
    def delete_user_paper_events(self, user_id: str, paper_id: str) -> int: ...


class ReaderSelectionRepository(Protocol):
    def list_selections(self, user_id: str, paper_id: str) -> list[ReaderSelection]: ...
    def get_selection(self, user_id: str, paper_id: str, selection_id: str) -> ReaderSelection | None: ...
    def upsert_selection(self, selection: ReaderSelection) -> ReaderSelection: ...
    def delete_selection(self, user_id: str, paper_id: str, selection_id: str) -> bool: ...
    def delete_user_paper_selections(self, user_id: str, paper_id: str) -> int: ...


class LocalJsonPaperReaderInteractionRepository(ReaderEventRepository, ReaderSelectionRepository):
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(
            path
            or os.environ.get("NEWSROOM_PAPER_READER_INTERACTIONS_PATH")
            or DEFAULT_PAPER_READER_INTERACTIONS_PATH
        )

    def append_event(self, event: ReaderEvent) -> ReaderEvent:
        with locked_json_file(self.path) as path:
            payload = self._read_payload_unlocked(path)
            events = [ReaderEvent.from_dict(item) for item in _sequence(payload.get("events")) if isinstance(item, Mapping)]
            events.append(event)
            payload["events"] = [
                item.to_dict()
                for item in sorted(events, key=lambda item: (item.createdAt or datetime.min.replace(tzinfo=UTC), item.eventId))
            ]
            self._write_payload_unlocked(path, payload)
        return event

    def append_event_and_update_selection(
        self,
        event: ReaderEvent,
        selection_updater: Callable[[ReaderSelection | None], ReaderSelection | None] | None,
    ) -> tuple[ReaderEvent, ReaderSelection | None]:
        with locked_json_file(self.path) as path:
            payload = self._read_payload_unlocked(path)
            events = [ReaderEvent.from_dict(item) for item in _sequence(payload.get("events")) if isinstance(item, Mapping)]
            events.append(event)
            payload["events"] = [
                item.to_dict()
                for item in sorted(events, key=lambda item: (item.createdAt or datetime.min.replace(tzinfo=UTC), item.eventId))
            ]
            next_selection: ReaderSelection | None = None
            if selection_updater is not None and event.selectionId is not None:
                selections = {
                    selection_key(item.userId, item.paperId, item.selectionId): item
                    for item in self._selections_from_payload(payload)
                }
                key = selection_key(event.userId, event.paperId, event.selectionId)
                next_selection = selection_updater(selections.get(key))
                selections.pop(key, None)
                if next_selection is not None:
                    selections[
                        selection_key(next_selection.userId, next_selection.paperId, next_selection.selectionId)
                    ] = next_selection
                payload["selections"] = [
                    item.to_dict()
                    for item in sorted(selections.values(), key=lambda value: (value.userId, value.paperId, value.selectionId))
                ]
            self._write_payload_unlocked(path, payload)
        return event, next_selection

    def list_events(self, user_id: str, paper_id: str, *, limit: int | None = None) -> list[ReaderEvent]:
        events = [
            event
            for event in self._events()
            if event.userId == user_id and event.paperId == paper_id
        ]
        events = sorted(events, key=lambda item: (item.createdAt or datetime.min.replace(tzinfo=UTC), item.eventId))
        if limit is not None:
            return events[-max(0, int(limit)) :]
        return events

    def list_unprocessed_events(self, *, limit: int = 100, user_id: str | None = None, paper_id: str | None = None) -> list[ReaderEvent]:
        payload = self._read_payload()
        processed_ids = {str(item) for item in _sequence(payload.get("processedEventIds"))}
        events = []
        for event in self._events_from_payload(payload):
            if event.eventId in processed_ids:
                continue
            if user_id is not None and event.userId != user_id:
                continue
            if paper_id is not None and event.paperId != paper_id:
                continue
            events.append(event)
        return sorted(events, key=lambda item: (item.createdAt or datetime.min.replace(tzinfo=UTC), item.eventId))[: max(0, int(limit))]

    def mark_events_processed(self, event_ids: Sequence[str]) -> None:
        with locked_json_file(self.path) as path:
            payload = self._read_payload_unlocked(path)
            processed_ids = {str(item) for item in _sequence(payload.get("processedEventIds"))}
            processed_ids.update(str(event_id) for event_id in event_ids if str(event_id).strip())
            payload["processedEventIds"] = sorted(processed_ids)
            self._write_payload_unlocked(path, payload)

    def delete_user_paper_events(self, user_id: str, paper_id: str) -> int:
        with locked_json_file(self.path) as path:
            payload = self._read_payload_unlocked(path)
            events = [event for event in self._events_from_payload(payload) if not (event.userId == user_id and event.paperId == paper_id)]
            deleted = len(_sequence(payload.get("events"))) - len(events)
            payload["events"] = [event.to_dict() for event in events]
            self._write_payload_unlocked(path, payload)
        return deleted

    def list_selections(self, user_id: str, paper_id: str) -> list[ReaderSelection]:
        return sorted(
            [
                selection
                for selection in self._selections()
                if selection.userId == user_id and selection.paperId == paper_id
            ],
            key=lambda item: (item.updatedAt or item.createdAt or datetime.min.replace(tzinfo=UTC), item.selectionId),
        )

    def get_selection(self, user_id: str, paper_id: str, selection_id: str) -> ReaderSelection | None:
        for selection in self._selections():
            if selection.userId == user_id and selection.paperId == paper_id and selection.selectionId == selection_id:
                return selection
        return None

    def upsert_selection(self, selection: ReaderSelection) -> ReaderSelection:
        with locked_json_file(self.path) as path:
            payload = self._read_payload_unlocked(path)
            selections = {
                selection_key(item.userId, item.paperId, item.selectionId): item
                for item in self._selections_from_payload(payload)
            }
            selections[selection_key(selection.userId, selection.paperId, selection.selectionId)] = selection
            payload["selections"] = [
                item.to_dict()
                for item in sorted(selections.values(), key=lambda value: (value.userId, value.paperId, value.selectionId))
            ]
            self._write_payload_unlocked(path, payload)
        return selection

    def delete_selection(self, user_id: str, paper_id: str, selection_id: str) -> bool:
        with locked_json_file(self.path) as path:
            payload = self._read_payload_unlocked(path)
            key = selection_key(user_id, paper_id, selection_id)
            selections = {
                selection_key(item.userId, item.paperId, item.selectionId): item
                for item in self._selections_from_payload(payload)
            }
            if key not in selections:
                return False
            del selections[key]
            payload["selections"] = [item.to_dict() for item in selections.values()]
            self._write_payload_unlocked(path, payload)
        return True

    def delete_user_paper_selections(self, user_id: str, paper_id: str) -> int:
        with locked_json_file(self.path) as path:
            payload = self._read_payload_unlocked(path)
            selections = [
                selection
                for selection in self._selections_from_payload(payload)
                if not (selection.userId == user_id and selection.paperId == paper_id)
            ]
            deleted = len(_sequence(payload.get("selections"))) - len(selections)
            payload["selections"] = [selection.to_dict() for selection in selections]
            self._write_payload_unlocked(path, payload)
        return deleted

    def _events(self) -> list[ReaderEvent]:
        return self._events_from_payload(self._read_payload())

    def _selections(self) -> list[ReaderSelection]:
        return self._selections_from_payload(self._read_payload())

    def _events_from_payload(self, payload: Mapping[str, Any]) -> list[ReaderEvent]:
        return [ReaderEvent.from_dict(item) for item in _sequence(payload.get("events")) if isinstance(item, Mapping)]

    def _selections_from_payload(self, payload: Mapping[str, Any]) -> list[ReaderSelection]:
        return [ReaderSelection.from_dict(item) for item in _sequence(payload.get("selections")) if isinstance(item, Mapping)]

    def _read_payload(self) -> dict[str, Any]:
        with locked_json_file(self.path) as path:
            return self._read_payload_unlocked(path)

    def _read_payload_unlocked(self, path: Path) -> dict[str, Any]:
        payload = read_json_object_unlocked(path, default=_default_payload(), strict=True)
        if not isinstance(payload, dict):
            return _default_payload()
        payload.setdefault("schemaVersion", "paper_reader_interactions.v1")
        payload.setdefault("events", [])
        payload.setdefault("selections", [])
        payload.setdefault("processedEventIds", [])
        return payload

    def _write_payload(self, payload: Mapping[str, Any]) -> None:
        with locked_json_file(self.path) as path:
            self._write_payload_unlocked(path, payload)

    def _write_payload_unlocked(self, path: Path, payload: Mapping[str, Any]) -> None:
        write_json_object_unlocked(path, dict(payload))


class PaperReaderInteractionApplicationService:
    def __init__(
        self,
        *,
        event_repository: ReaderEventRepository | None = None,
        selection_repository: ReaderSelectionRepository | None = None,
        store_path: str | Path | None = None,
        event_publisher: Any | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        repository = LocalJsonPaperReaderInteractionRepository(store_path)
        self.event_repository = event_repository or repository
        self.selection_repository = selection_repository or repository
        self.event_publisher = event_publisher
        self.clock = clock or (lambda: datetime.now(UTC))

    def record_event(self, *, user_id: str, paper_id: str, payload: Mapping[str, Any]) -> ReaderEventRecordResult:
        event = self._event_from_payload(user_id=user_id, paper_id=paper_id, payload=payload)
        selection_updater = self._selection_updater_for_event(event)
        atomic_recorder = getattr(self.event_repository, "append_event_and_update_selection", None)
        if callable(atomic_recorder) and self.event_repository is self.selection_repository:
            stored_event, selection = atomic_recorder(event, selection_updater)
        else:
            stored_event = self.event_repository.append_event(event)
            selection = None
            if selection_updater is not None and event.selectionId is not None:
                current = self.selection_repository.get_selection(event.userId, event.paperId, event.selectionId)
                next_selection = selection_updater(current)
                if next_selection is None:
                    self.selection_repository.delete_selection(event.userId, event.paperId, event.selectionId)
                else:
                    selection = self.selection_repository.upsert_selection(next_selection)
        self._publish_recorded_event(stored_event)
        return ReaderEventRecordResult(
            event=stored_event,
            selection=selection,
            materialSummary=self.material_summary(user_id=user_id, paper_id=paper_id),
        )

    def create_selection(self, *, user_id: str, paper_id: str, payload: Mapping[str, Any]) -> ReaderEventRecordResult:
        request = dict(payload)
        request["type"] = "selection_created"
        return self.record_event(user_id=user_id, paper_id=paper_id, payload=request)

    def patch_selection(self, *, user_id: str, paper_id: str, selection_id: str, patch: Mapping[str, Any]) -> ReaderEventRecordResult:
        current = self.selection_repository.get_selection(user_id, paper_id, selection_id)
        if current is None:
            raise ReaderSelectionNotFoundError(selection_id)
        event_type, event_payload = _event_patch_from_selection_patch(current, patch)
        request = {
            "type": event_type,
            "selectionId": selection_id,
            "target": current.target.to_dict(),
            "sectionId": current.sectionId,
            "paragraphId": current.paragraphId,
            "selectedText": current.selectedText,
            "surroundingText": current.surroundingText,
            "payload": event_payload,
        }
        return self.record_event(user_id=user_id, paper_id=paper_id, payload=request)

    def material_summary(self, *, user_id: str, paper_id: str, event_limit: int | None = 200) -> ReaderMaterialSummary:
        return ReaderMaterialSummary(
            paperId=paper_id,
            userId=user_id,
            selections=self.selection_repository.list_selections(user_id, paper_id),
            events=self.event_repository.list_events(user_id, paper_id, limit=event_limit),
        )

    def delete_user_paper_materials(self, *, user_id: str, paper_id: str) -> dict[str, int]:
        return {
            "eventsDeleted": self.event_repository.delete_user_paper_events(user_id, paper_id),
            "selectionsDeleted": self.selection_repository.delete_user_paper_selections(user_id, paper_id),
        }

    def _event_from_payload(self, *, user_id: str, paper_id: str, payload: Mapping[str, Any]) -> ReaderEvent:
        event_type = _reader_event_type(payload.get("type") or payload.get("eventType"))
        target = ReaderBlockTarget.from_dict(payload.get("target") if isinstance(payload.get("target"), Mapping) else None)
        section_id = _optional_text(payload.get("sectionId")) or (target.sectionId if target else None)
        paragraph_id = _optional_text(payload.get("paragraphId")) or (target.paragraphId if target else None)
        selection_id = _optional_text(payload.get("selectionId"))
        if selection_id is None and event_type in SELECTION_EVENT_TYPES:
            selection_id = f"sel_{secrets.token_hex(10)}"
        if target is None and event_type in SELECTION_EVENT_TYPES:
            target = ReaderBlockTarget(
                targetType="text_selection",
                sectionId=section_id,
                paragraphId=paragraph_id,
                pageNumber=_optional_positive_int(payload.get("pageNumber"), field_name="pageNumber"),
            )
        return ReaderEvent(
            eventId=_optional_text(payload.get("eventId")) or f"reader_event_{secrets.token_hex(12)}",
            type=event_type,
            userId=user_id,
            paperId=paper_id,
            selectionId=selection_id,
            target=target,
            sectionId=section_id,
            paragraphId=paragraph_id,
            selectedText=_optional_limited_text(payload.get("selectedText"), max_length=MAX_SELECTED_TEXT_LENGTH, field_name="selectedText"),
            surroundingText=_optional_limited_text(payload.get("surroundingText"), max_length=MAX_SURROUNDING_TEXT_LENGTH, field_name="surroundingText"),
            payload=_safe_payload_map(payload.get("payload")),
            createdAt=self.clock(),
        )

    def _selection_updater_for_event(
        self,
        event: ReaderEvent,
    ) -> Callable[[ReaderSelection | None], ReaderSelection | None] | None:
        if event.type not in SELECTION_EVENT_TYPES or event.selectionId is None:
            return None

        def update(current: ReaderSelection | None) -> ReaderSelection | None:
            selection = self._selection_from_event(event, current)
            if selection is None:
                return None
            return self._stored_selection_after_event(event, selection)

        return update

    def _selection_from_event(self, event: ReaderEvent, current: ReaderSelection | None) -> ReaderSelection | None:
        if event.type not in SELECTION_EVENT_TYPES or event.selectionId is None:
            return None
        now = event.createdAt or self.clock()
        target = event.target or (current.target if current else ReaderBlockTarget(targetType="text_selection"))
        base = current or ReaderSelection(
            selectionId=event.selectionId,
            userId=event.userId,
            paperId=event.paperId,
            target=target,
            createdAt=now,
            updatedAt=now,
        )
        payload = event.payload or {}
        selected_text = event.selectedText if event.selectedText is not None else base.selectedText
        surrounding_text = event.surroundingText if event.surroundingText is not None else base.surroundingText
        section_id = event.sectionId or target.sectionId or base.sectionId
        paragraph_id = event.paragraphId or target.paragraphId or base.paragraphId
        updated = replace(
            base,
            target=target,
            sectionId=section_id,
            sectionTitle=_optional_limited_text(payload.get("sectionTitle"), max_length=200, field_name="sectionTitle") or base.sectionTitle,
            paragraphId=paragraph_id,
            selectedText=selected_text,
            surroundingText=surrounding_text,
            updatedAt=now,
        )
        if event.type == "note_updated":
            updated = replace(
                updated,
                noteText=_optional_limited_text(payload.get("noteText"), max_length=MAX_NOTE_TEXT_LENGTH, field_name="noteText"),
            )
        elif event.type == "explanation_generated":
            updated = replace(
                updated,
                explained=True,
                explainQuestion=_question_from_payload(payload, "explainQuestion"),
            )
        elif event.type == "example_generated":
            updated = replace(
                updated,
                exampled=True,
                exampleQuestion=_question_from_payload(payload, "exampleQuestion"),
            )
        elif event.type in {"figure_explanation_generated", "table_explanation_generated"}:
            updated = replace(updated, explained=True, explainQuestion=_question_from_payload(payload, "explainQuestion"))
        elif event.type in {"figure_explanation_requested", "table_explanation_requested"}:
            updated = replace(updated, explainQuestion=_question_from_payload(payload, "explainQuestion"))
        elif event.type == "confusion_marked":
            updated = replace(updated, confused=True)
        elif event.type == "confusion_unmarked":
            updated = replace(updated, confused=False)
        return updated

    def _persist_selection_after_event(self, event: ReaderEvent, selection: ReaderSelection) -> ReaderSelection | None:
        stored = self._stored_selection_after_event(event, selection)
        if stored is None:
            self.selection_repository.delete_selection(selection.userId, selection.paperId, selection.selectionId)
            return None
        return self.selection_repository.upsert_selection(stored)

    def _stored_selection_after_event(self, event: ReaderEvent, selection: ReaderSelection) -> ReaderSelection | None:
        if event.type in {"selection_discarded", "confusion_unmarked"} and not selection.has_material:
            return None
        if event.type == "note_updated" and not selection.noteText and not selection.has_material:
            return None
        return selection

    def _publish_recorded_event(self, event: ReaderEvent) -> None:
        if self.event_publisher is None:
            return
        publish = getattr(self.event_publisher, "publish", None)
        if not callable(publish):
            return
        publish(
            Event(
                event_type="paper_reader.event_recorded",
                source="paper_reader",
                component="paper_reader",
                payload=event.to_dict(),
                metadata={"paperId": event.paperId, "userId": event.userId},
            )
        )


def selection_key(user_id: str, paper_id: str, selection_id: str) -> str:
    return f"{user_id}::{paper_id}::{selection_id}"


def _default_payload() -> dict[str, Any]:
    return {"schemaVersion": "paper_reader_interactions.v1", "events": [], "selections": [], "processedEventIds": []}


def _event_patch_from_selection_patch(current: ReaderSelection, patch: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    payload = dict(patch)
    action_names = _selection_patch_action_names(patch)
    if len(action_names) > 1:
        raise ValueError("selection patch must contain only one reader action")
    if "noteText" in patch:
        return "note_updated", {"noteText": patch.get("noteText"), "sectionTitle": current.sectionTitle}
    if "explained" in patch:
        if not bool(patch.get("explained")):
            raise ValueError("explained can only be set to true")
        return "explanation_generated", {
            "explainQuestion": patch.get("explainQuestion") or patch.get("question"),
            "answer": patch.get("answer"),
            "sectionTitle": current.sectionTitle,
        }
    if "exampled" in patch:
        if not bool(patch.get("exampled")):
            raise ValueError("exampled can only be set to true")
        return "example_generated", {
            "exampleQuestion": patch.get("exampleQuestion") or patch.get("question"),
            "example": patch.get("example"),
            "sectionTitle": current.sectionTitle,
        }
    if "confused" in patch:
        return ("confusion_marked" if bool(patch.get("confused")) else "confusion_unmarked"), {"sectionTitle": current.sectionTitle}
    return "selection_updated", payload


def _selection_patch_action_names(patch: Mapping[str, Any]) -> list[str]:
    names: list[str] = []
    for key in ("noteText", "explained", "exampled", "confused"):
        if key in patch:
            names.append(key)
    return names


def _question_from_payload(payload: Mapping[str, Any], field_name: str) -> str | None:
    return _optional_limited_text(
        payload.get(field_name) or payload.get("question") or payload.get("userQuestion"),
        max_length=MAX_QUESTION_LENGTH,
        field_name=field_name,
    )


def _reader_event_type(value: Any) -> ReaderEventType:
    text = str(value or "").strip()
    if text not in VALID_EVENT_TYPES:
        raise ValueError(f"type must be one of: {', '.join(sorted(VALID_EVENT_TYPES))}")
    return text  # type: ignore[return-value]


def _target_type(value: Any) -> ReaderTargetType:
    text = str(value or "").strip()
    if text not in VALID_TARGET_TYPES:
        raise ValueError(f"targetType must be one of: {', '.join(sorted(VALID_TARGET_TYPES))}")
    return text  # type: ignore[return-value]


def _safe_payload_map(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("payload must be an object")
    result: dict[str, Any] = {}
    for key, item in value.items():
        text_key = str(key).strip()
        if not text_key:
            continue
        result[text_key] = _safe_payload_value(item)
    return result


def _safe_payload_value(value: Any) -> Any:
    if isinstance(value, str):
        return value[:MAX_PAYLOAD_TEXT_LENGTH]
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, Mapping):
        return {str(key): _safe_payload_value(item) for key, item in list(value.items())[:100]}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_safe_payload_value(item) for item in list(value)[:100]]
    return str(value)[:MAX_PAYLOAD_TEXT_LENGTH]


def _source_box(value: Any) -> dict[str, float] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("target.sourceBox must be an object")
    result: dict[str, float] = {}
    for key in ("x0", "y0", "x1", "y1", "page"):
        if key in value:
            result[key] = float(value[key])
    return result or None


def _optional_limited_text(value: Any, *, max_length: int, field_name: str) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) > max_length:
        raise ValueError(f"{field_name} must be {max_length} characters or fewer")
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_positive_int(value: Any, *, field_name: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc
    if number < 1:
        raise ValueError(f"{field_name} must be greater than zero")
    return number


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []


def _format_datetime(value: datetime) -> str:
    actual = value if value.tzinfo else value.replace(tzinfo=UTC)
    return actual.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_optional_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)


__all__ = [
    "HIGH_VALUE_EVENT_TYPES",
    "LocalJsonPaperReaderInteractionRepository",
    "PaperReaderInteractionApplicationService",
    "ReaderBlockTarget",
    "ReaderEvent",
    "ReaderEventRecordResult",
    "ReaderEventRepository",
    "ReaderEventType",
    "ReaderLearningSignal",
    "ReaderMaterialSummary",
    "ReaderSelection",
    "ReaderSelectionNotFoundError",
    "ReaderSelectionRepository",
    "ReaderTargetType",
]
