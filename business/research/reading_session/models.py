from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from business.foundation import PrimitiveModel
from business.research.domain.common import ensure_utc, require_text, unique_texts


ReadingEventType = Literal[
    "highlight_created",
    "note_created",
    "question_asked",
    "answer_generated",
    "bookmark_created",
    "confusion_marked",
    "section_selected",
    "reading_note_requested",
]


class ReadingEvent(PrimitiveModel):
    event_id: str
    event_type: ReadingEventType
    paper_id: str
    user_id: str
    target_ref: str | None = None
    text: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("event_id", "paper_id", "user_id")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "reading event fields")

    @model_validator(mode="after")
    def _normalize(self) -> "ReadingEvent":
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))
        object.__setattr__(self, "source_refs", unique_texts(self.source_refs))
        return self


class ReadingSession(PrimitiveModel):
    session_id: str
    paper_id: str
    user_id: str
    events: list[ReadingEvent] = Field(default_factory=list)
    selected_refs: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("session_id", "paper_id", "user_id")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "reading session fields")

    @model_validator(mode="after")
    def _normalize(self) -> "ReadingSession":
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))
        object.__setattr__(self, "updated_at", ensure_utc(self.updated_at))
        object.__setattr__(self, "selected_refs", unique_texts(self.selected_refs))
        object.__setattr__(self, "source_refs", unique_texts(self.source_refs))
        for event in self.events:
            if event.paper_id != self.paper_id or event.user_id != self.user_id:
                raise ValueError("reading session events must match session paper and user")
        return self


class ReadingNote(PrimitiveModel):
    reading_note_id: str
    paper_id: str
    user_id: str
    selected_highlights: list[str] = Field(default_factory=list)
    selected_notes: list[str] = Field(default_factory=list)
    selected_questions: list[str] = Field(default_factory=list)
    generated_summary: str
    key_takeaways: list[str] = Field(default_factory=list)
    method_notes: list[str] = Field(default_factory=list)
    benchmark_notes: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    source_refs: list[str]
    user_selection_refs: list[str]
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("reading_note_id", "paper_id", "user_id", "generated_summary")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return require_text(value, "reading note fields")

    @model_validator(mode="after")
    def _normalize_and_require_refs(self) -> "ReadingNote":
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))
        for field_name in (
            "selected_highlights",
            "selected_notes",
            "selected_questions",
            "key_takeaways",
            "method_notes",
            "benchmark_notes",
            "open_questions",
            "source_refs",
            "user_selection_refs",
        ):
            object.__setattr__(self, field_name, unique_texts(getattr(self, field_name)))
        if not self.source_refs:
            raise ValueError("reading note requires source refs")
        if not self.user_selection_refs:
            raise ValueError("reading note requires user selection refs")
        return self


__all__ = ["ReadingEvent", "ReadingEventType", "ReadingNote", "ReadingSession"]
