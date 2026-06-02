from __future__ import annotations

import os
import secrets
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from pathlib import Path
from typing import Any, Literal, Protocol

from interfaces.services.json_file_store import locked_json_file, read_json_object_unlocked, write_json_object_unlocked


DEFAULT_PAPER_READER_NOTES_PATH = ".newsroom/papers/reader-notes.json"
PaperReaderNoteKind = Literal["bookmark", "highlight", "note"]
PaperReaderNoteColor = Literal["yellow", "green", "blue", "pink"]
VALID_NOTE_KINDS = {"bookmark", "highlight", "note"}
VALID_NOTE_COLORS = {"yellow", "green", "blue", "pink"}
MAX_QUOTE_LENGTH = 2000
MAX_NOTE_TEXT_LENGTH = 4000
MAX_LABEL_LENGTH = 200


class PaperReaderNoteNotFoundError(Exception):
    """Raised when a reader note does not exist for the current user."""


@dataclass(frozen=True)
class PaperReaderNote:
    noteId: str
    userId: str
    paperId: str
    kind: PaperReaderNoteKind
    pageNumber: int
    color: PaperReaderNoteColor = "yellow"
    quote: str | None = None
    noteText: str | None = None
    label: str | None = None
    anchor: dict[str, Any] | None = None
    createdAt: datetime | None = None
    updatedAt: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        created_at = self.createdAt or datetime.now(UTC)
        updated_at = self.updatedAt or created_at
        payload: dict[str, Any] = {
            "noteId": self.noteId,
            "userId": self.userId,
            "paperId": self.paperId,
            "kind": self.kind,
            "pageNumber": self.pageNumber,
            "color": self.color,
            "createdAt": _format_datetime(created_at),
            "updatedAt": _format_datetime(updated_at),
        }
        if self.quote:
            payload["quote"] = self.quote
        if self.noteText:
            payload["noteText"] = self.noteText
        if self.label:
            payload["label"] = self.label
        if self.anchor:
            payload["anchor"] = self.anchor
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PaperReaderNote":
        return cls(
            noteId=str(payload["noteId"]),
            userId=str(payload["userId"]),
            paperId=str(payload["paperId"]),
            kind=_note_kind(payload.get("kind")),
            pageNumber=_page_number(payload.get("pageNumber")),
            color=_note_color(payload.get("color") or "yellow"),
            quote=_optional_limited_text(payload.get("quote"), max_length=MAX_QUOTE_LENGTH, field_name="quote"),
            noteText=_optional_limited_text(payload.get("noteText"), max_length=MAX_NOTE_TEXT_LENGTH, field_name="noteText"),
            label=_optional_limited_text(payload.get("label"), max_length=MAX_LABEL_LENGTH, field_name="label"),
            anchor=_safe_anchor(payload.get("anchor")),
            createdAt=_parse_optional_datetime(payload.get("createdAt")),
            updatedAt=_parse_optional_datetime(payload.get("updatedAt")),
        )


class PaperReaderNotesRepository(Protocol):
    def list_notes(self, user_id: str, paper_id: str) -> list[PaperReaderNote]: ...
    def get_note(self, user_id: str, paper_id: str, note_id: str) -> PaperReaderNote | None: ...
    def upsert_note(self, note: PaperReaderNote) -> PaperReaderNote: ...
    def update_note(
        self,
        user_id: str,
        paper_id: str,
        note_id: str,
        updater: Callable[[PaperReaderNote], PaperReaderNote],
    ) -> PaperReaderNote | None: ...
    def delete_note(self, user_id: str, paper_id: str, note_id: str) -> bool: ...


class LocalJsonPaperReaderNotesRepository:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or os.environ.get("NEWSROOM_PAPER_READER_NOTES_PATH") or DEFAULT_PAPER_READER_NOTES_PATH)

    def list_notes(self, user_id: str, paper_id: str) -> list[PaperReaderNote]:
        return sorted(
            [
                note
                for note in self._read_records().values()
                if note.userId == user_id and note.paperId == paper_id
            ],
            key=lambda item: (item.pageNumber, item.createdAt or datetime.min.replace(tzinfo=UTC), item.noteId),
        )

    def get_note(self, user_id: str, paper_id: str, note_id: str) -> PaperReaderNote | None:
        note = self._read_records().get(note_id)
        if note is None or note.userId != user_id or note.paperId != paper_id:
            return None
        return note

    def upsert_note(self, note: PaperReaderNote) -> PaperReaderNote:
        with locked_json_file(self.path) as path:
            records = self._read_records_unlocked(path)
            records[note.noteId] = note
            self._write_records_unlocked(path, records)
        return note

    def update_note(
        self,
        user_id: str,
        paper_id: str,
        note_id: str,
        updater: Callable[[PaperReaderNote], PaperReaderNote],
    ) -> PaperReaderNote | None:
        with locked_json_file(self.path) as path:
            records = self._read_records_unlocked(path)
            current = records.get(note_id)
            if current is None or current.userId != user_id or current.paperId != paper_id:
                return None
            next_note = updater(current)
            records[note_id] = next_note
            self._write_records_unlocked(path, records)
        return next_note

    def delete_note(self, user_id: str, paper_id: str, note_id: str) -> bool:
        with locked_json_file(self.path) as path:
            records = self._read_records_unlocked(path)
            note = records.get(note_id)
            if note is None or note.userId != user_id or note.paperId != paper_id:
                return False
            del records[note_id]
            self._write_records_unlocked(path, records)
        return True

    def _read_records(self) -> dict[str, PaperReaderNote]:
        with locked_json_file(self.path) as path:
            return self._read_records_unlocked(path)

    def _read_records_unlocked(self, path: Path) -> dict[str, PaperReaderNote]:
        payload = read_json_object_unlocked(path, default={"notes": []}, strict=True)
        notes = [PaperReaderNote.from_dict(item) for item in payload.get("notes", [])]
        return {note.noteId: note for note in notes}

    def _write_records_unlocked(self, path: Path, records: dict[str, PaperReaderNote]) -> None:
        payload = {
            "schemaVersion": "paper_reader_notes.v1",
            "notes": [
                record.to_dict()
                for record in sorted(records.values(), key=lambda item: (item.userId, item.paperId, item.noteId))
            ],
        }
        write_json_object_unlocked(path, payload)


class PaperReaderNotesApplicationService:
    def __init__(
        self,
        repository: PaperReaderNotesRepository | None = None,
        *,
        store_path: str | Path | None = None,
    ) -> None:
        self.repository = repository or LocalJsonPaperReaderNotesRepository(store_path)

    def list_notes(self, *, user_id: str, paper_id: str) -> list[PaperReaderNote]:
        return self.repository.list_notes(user_id, paper_id)

    def create_note(self, *, user_id: str, paper_id: str, payload: dict[str, Any]) -> PaperReaderNote:
        now = datetime.now(UTC)
        note = PaperReaderNote(
            noteId=f"note_{secrets.token_hex(10)}",
            userId=user_id,
            paperId=paper_id,
            kind=_note_kind(payload.get("kind")),
            pageNumber=_page_number(payload.get("pageNumber")),
            color=_note_color(payload.get("color") or "yellow"),
            quote=_optional_limited_text(payload.get("quote"), max_length=MAX_QUOTE_LENGTH, field_name="quote"),
            noteText=_optional_limited_text(payload.get("noteText"), max_length=MAX_NOTE_TEXT_LENGTH, field_name="noteText"),
            label=_optional_limited_text(payload.get("label"), max_length=MAX_LABEL_LENGTH, field_name="label"),
            anchor=_safe_anchor(payload.get("anchor")),
            createdAt=now,
            updatedAt=now,
        )
        _validate_note_payload(note)
        return self.repository.upsert_note(note)

    def patch_note(self, *, user_id: str, paper_id: str, note_id: str, patch: dict[str, Any]) -> PaperReaderNote:
        note = self.repository.update_note(
            user_id,
            paper_id,
            note_id,
            lambda current: _apply_note_patch(current, patch),
        )
        if note is None:
            raise PaperReaderNoteNotFoundError(note_id)
        return note

    def delete_note(self, *, user_id: str, paper_id: str, note_id: str) -> bool:
        deleted = self.repository.delete_note(user_id, paper_id, note_id)
        if not deleted:
            raise PaperReaderNoteNotFoundError(note_id)
        return True


def _validate_note_payload(note: PaperReaderNote) -> None:
    if note.kind in {"highlight", "note"} and not note.quote:
        raise ValueError("quote is required for highlight and note")
    if note.kind == "note" and not note.noteText:
        raise ValueError("noteText is required for note")


def _apply_note_patch(current: PaperReaderNote, patch: dict[str, Any]) -> PaperReaderNote:
    next_note = current
    if "color" in patch:
        next_note = replace(next_note, color=_note_color(patch["color"]))
    if "quote" in patch:
        next_note = replace(
            next_note,
            quote=_optional_limited_text(patch.get("quote"), max_length=MAX_QUOTE_LENGTH, field_name="quote"),
        )
    if "noteText" in patch:
        next_note = replace(
            next_note,
            noteText=_optional_limited_text(patch.get("noteText"), max_length=MAX_NOTE_TEXT_LENGTH, field_name="noteText"),
        )
    if "label" in patch:
        next_note = replace(
            next_note,
            label=_optional_limited_text(patch.get("label"), max_length=MAX_LABEL_LENGTH, field_name="label"),
        )
    if "anchor" in patch:
        next_note = replace(next_note, anchor=_safe_anchor(patch.get("anchor")))
    next_note = replace(next_note, updatedAt=datetime.now(UTC))
    _validate_note_payload(next_note)
    return next_note


def _note_kind(value: Any) -> PaperReaderNoteKind:
    text = str(value or "").strip()
    if text not in VALID_NOTE_KINDS:
        raise ValueError("kind must be bookmark, highlight, or note")
    return text  # type: ignore[return-value]


def _note_color(value: Any) -> PaperReaderNoteColor:
    text = str(value or "").strip()
    if text not in VALID_NOTE_COLORS:
        raise ValueError("color must be yellow, green, blue, or pink")
    return text  # type: ignore[return-value]


def _page_number(value: Any) -> int:
    try:
        page_number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("pageNumber must be an integer") from exc
    if page_number < 1:
        raise ValueError("pageNumber must be greater than zero")
    return page_number


def _optional_limited_text(value: Any, *, max_length: int, field_name: str) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) > max_length:
        raise ValueError(f"{field_name} must be {max_length} characters or fewer")
    return text


def _safe_anchor(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("anchor must be an object")
    allowed = {"pageNumber", "quote", "rects", "textStart", "textEnd"}
    anchor: dict[str, Any] = {}
    for key in allowed:
        if key in value:
            anchor[key] = value[key]
    if "pageNumber" in anchor:
        anchor["pageNumber"] = _page_number(anchor["pageNumber"])
    if "quote" in anchor:
        anchor["quote"] = _optional_limited_text(anchor["quote"], max_length=MAX_QUOTE_LENGTH, field_name="quote")
    if "rects" in anchor:
        anchor["rects"] = _safe_rects(anchor["rects"])
    return anchor or None


def _safe_rects(value: Any) -> list[dict[str, float]]:
    if not isinstance(value, list):
        raise ValueError("anchor.rects must be an array")
    rects: list[dict[str, float]] = []
    for raw_rect in value[:20]:
        if not isinstance(raw_rect, dict):
            continue
        rect: dict[str, float] = {}
        for key in ("left", "top", "width", "height"):
            try:
                rect[key] = float(raw_rect[key])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"anchor.rects.{key} must be a number") from exc
        if rect["width"] >= 0 and rect["height"] >= 0:
            rects.append(rect)
    return rects


def _format_datetime(value: datetime) -> str:
    actual = value if value.tzinfo else value.replace(tzinfo=UTC)
    return actual.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_optional_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)
