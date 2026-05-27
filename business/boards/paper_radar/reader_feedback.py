from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from business.memory.intelligence_builder import stable_id
from business.memory.intelligence_models import (
    DecisionMemory,
    EventMemory,
    EvidenceMemory,
    PreferenceMemory,
)
from business.memory.intelligence_repository import IntelligenceMemoryRepository


HIGH_VALUE_READER_EVENT_TYPES = {
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


@dataclass(frozen=True)
class ReaderLearningSignal:
    signal_id: str
    signal_type: str
    paper_id: str
    event_id: str
    user_id: str | None = None
    selection_id: str | None = None
    target: dict[str, Any] = field(default_factory=dict)
    content: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "signal_type": self.signal_type,
            "paper_id": self.paper_id,
            "event_id": self.event_id,
            "user_id": self.user_id,
            "selection_id": self.selection_id,
            "target": dict(self.target),
            "content": self.content,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ReaderFeedbackIngestionResult:
    processed_event_ids: list[str]
    skipped_event_ids: list[str]
    signals: list[ReaderLearningSignal]
    evidence_count: int = 0
    decision_count: int = 0
    preference_count: int = 0
    event_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "processed_event_ids": list(self.processed_event_ids),
            "skipped_event_ids": list(self.skipped_event_ids),
            "processed_count": len(self.processed_event_ids),
            "skipped_count": len(self.skipped_event_ids),
            "signals": [signal.to_dict() for signal in self.signals],
            "memory": {
                "evidence_count": self.evidence_count,
                "decision_count": self.decision_count,
                "preference_count": self.preference_count,
                "event_count": self.event_count,
            },
        }


class PaperReaderFeedbackService:
    def __init__(self, repository: IntelligenceMemoryRepository | None = None) -> None:
        self.repository = repository

    def ingest_reader_events(self, events: Sequence[Mapping[str, Any]]) -> ReaderFeedbackIngestionResult:
        processed_event_ids: list[str] = []
        skipped_event_ids: list[str] = []
        signals: list[ReaderLearningSignal] = []
        evidence: list[EvidenceMemory] = []
        decisions: list[DecisionMemory] = []
        preferences: list[PreferenceMemory] = []
        memory_events: list[EventMemory] = []

        for event in events:
            event_id = _text(event.get("eventId") or event.get("event_id"))
            event_type = _text(event.get("type") or event.get("eventType") or event.get("event_type"))
            if not event_id or event_type not in HIGH_VALUE_READER_EVENT_TYPES:
                if event_id:
                    skipped_event_ids.append(event_id)
                continue
            signal = _signal_from_event(event, event_type=event_type, event_id=event_id)
            if signal is None:
                skipped_event_ids.append(event_id)
                continue
            signals.append(signal)
            processed_event_ids.append(event_id)
            evidence_item = _evidence_from_signal(event, signal)
            if evidence_item is not None:
                evidence.append(evidence_item)
            decision = _decision_from_signal(event, signal)
            if decision is not None:
                decisions.append(decision)
            preference = _preference_from_signal(event, signal)
            if preference is not None:
                preferences.append(preference)
            paper_event = _paper_event_from_signal(event, signal)
            if paper_event is not None:
                memory_events.append(paper_event)

        if self.repository is not None:
            if evidence:
                self.repository.save_evidence(evidence)
            if decisions:
                self.repository.save_decisions(decisions)
            if preferences:
                self.repository.save_preferences(preferences)
            if memory_events:
                self.repository.save_events(memory_events)

        return ReaderFeedbackIngestionResult(
            processed_event_ids=processed_event_ids,
            skipped_event_ids=skipped_event_ids,
            signals=signals,
            evidence_count=len(evidence),
            decision_count=len(decisions),
            preference_count=len(preferences),
            event_count=len(memory_events),
        )


def _signal_from_event(event: Mapping[str, Any], *, event_type: str, event_id: str) -> ReaderLearningSignal | None:
    paper_id = _text(event.get("paperId") or event.get("paper_id"))
    if not paper_id:
        return None
    payload = _mapping(event.get("payload"))
    selected_text = _text(event.get("selectedText") or event.get("selected_text"))
    content = _content_for_signal(event_type, selected_text=selected_text, payload=payload)
    if event_type != "reader_settings_changed" and not content:
        return None
    signal_type = _signal_type(event_type, target=_mapping(event.get("target")))
    return ReaderLearningSignal(
        signal_id=stable_id("reader-signal", event_id, signal_type, prefix="reader-signal"),
        signal_type=signal_type,
        paper_id=paper_id,
        event_id=event_id,
        user_id=_text(event.get("userId") or event.get("user_id")) or None,
        selection_id=_text(event.get("selectionId") or event.get("selection_id")) or None,
        target=_mapping(event.get("target")),
        content=content,
        metadata={
            "reader_event_type": event_type,
            "selected_text": selected_text,
            "surrounding_text": _text(event.get("surroundingText") or event.get("surrounding_text")),
            "payload": payload,
        },
    )


def _evidence_from_signal(event: Mapping[str, Any], signal: ReaderLearningSignal) -> EvidenceMemory | None:
    if signal.signal_type == "reader_settings_preference":
        return None
    source_urls = _source_urls(event)
    title = _evidence_title(signal)
    summary = signal.content or title
    return EvidenceMemory(
        evidence_id=stable_id("reader-evidence", signal.signal_id, prefix="evidence"),
        run_id=_run_id(signal),
        title=title,
        summary=summary,
        source_urls=source_urls,
        source_item_ids=[signal.event_id],
        confidence=0.9,
        category="reader_feedback",
        topic="paper_reader",
        source_name="Open Reader",
        source_id="paper_reader",
        fetched_at=_event_time(event),
        metadata={
            **signal.metadata,
            "paper_id": signal.paper_id,
            "user_id": signal.user_id,
            "selection_id": signal.selection_id,
            "signal_type": signal.signal_type,
            "target": signal.target,
        },
    )


def _decision_from_signal(event: Mapping[str, Any], signal: ReaderLearningSignal) -> DecisionMemory | None:
    event_type = str(signal.metadata.get("reader_event_type") or "")
    if event_type not in {
        "explanation_generated",
        "example_generated",
        "confusion_marked",
        "confusion_unmarked",
        "figure_explanation_generated",
        "table_explanation_generated",
    }:
        return None
    decision = {
        "confusion_marked": "confused",
        "confusion_unmarked": "resolved",
    }.get(event_type, "confirmed")
    return DecisionMemory(
        decision_id=stable_id("reader-decision", signal.signal_id, prefix="decision"),
        decision_type=f"reader_{event_type}",
        target_type=_target_type(signal),
        target_id=_target_id(signal),
        decision=decision,
        run_id=_run_id(signal),
        reason=signal.content,
        agent_id=signal.user_id,
        workflow_id="paper_reader_feedback",
        created_at=_event_time(event),
        metadata=signal.to_dict(),
    )


def _preference_from_signal(event: Mapping[str, Any], signal: ReaderLearningSignal) -> PreferenceMemory | None:
    if not signal.user_id:
        return None
    event_type = str(signal.metadata.get("reader_event_type") or "")
    preference_type: str | None = None
    content: str | None = None
    if event_type == "reader_settings_changed":
        preference_type = "reader_settings_preference"
        content = json_dumps(signal.metadata.get("payload") or {})
    elif event_type == "example_generated":
        preference_type = "reader_example_preference"
        content = signal.content
    elif event_type in {"figure_explanation_requested", "table_explanation_requested"}:
        preference_type = "reader_multimodal_explanation_preference"
        content = signal.content
    if not preference_type or not content:
        return None
    return PreferenceMemory(
        preference_id=stable_id("reader-preference", signal.user_id, preference_type, signal.signal_id, prefix="preference"),
        owner_type="user",
        owner_id=signal.user_id,
        preference_type=preference_type,
        content=content,
        weight=0.8,
        source="paper_reader_feedback",
        created_at=_event_time(event),
        metadata=signal.to_dict(),
    )


def _paper_event_from_signal(event: Mapping[str, Any], signal: ReaderLearningSignal) -> EventMemory | None:
    if signal.signal_type not in {"reader_confusion_point", "reader_figure_or_table_need"}:
        return None
    target_id = _target_id(signal)
    return EventMemory(
        event_id=stable_id("reader-paper-event", signal.paper_id, signal.signal_type, target_id, signal.event_id, prefix="event"),
        event_type="general_news",
        title=f"Reader feedback hotspot for {signal.paper_id}",
        summary=signal.content or signal.signal_type,
        run_id=_run_id(signal),
        event_time=_event_time(event),
        topic="paper_reader",
        impact_score=0.2,
        novelty_score=0.5,
        metadata={
            **signal.to_dict(),
            "paper_level_aggregate_candidate": True,
        },
    )


def _signal_type(event_type: str, *, target: Mapping[str, Any]) -> str:
    target_type = _text(target.get("targetType"))
    if event_type == "note_updated":
        return "reader_note_insight"
    if event_type in {"confusion_marked", "confusion_unmarked"}:
        return "reader_confusion_point"
    if event_type in {"explanation_generated", "figure_explanation_generated", "table_explanation_generated"}:
        return "reader_explanation_need"
    if event_type == "example_generated":
        return "reader_example_preference"
    if event_type == "reader_settings_changed":
        return "reader_settings_preference"
    if target_type in {"figure", "table"} or event_type.startswith(("figure_", "table_")):
        return "reader_figure_or_table_need"
    return "reader_content_hotspot"


def _content_for_signal(event_type: str, *, selected_text: str, payload: Mapping[str, Any]) -> str | None:
    if event_type == "note_updated":
        return _text(payload.get("noteText")) or selected_text
    if event_type == "example_generated":
        return _first_text(payload.get("exampleQuestion"), payload.get("question"), payload.get("userQuestion"), payload.get("example"), selected_text)
    if event_type in {"explanation_generated", "figure_explanation_generated", "table_explanation_generated"}:
        return _first_text(payload.get("explainQuestion"), payload.get("question"), payload.get("userQuestion"), payload.get("answer"), selected_text)
    if event_type in {"figure_explanation_requested", "table_explanation_requested"}:
        return _first_text(payload.get("question"), payload.get("userQuestion"), selected_text)
    if event_type == "confusion_marked":
        return selected_text or _text(payload.get("reason"))
    if event_type == "confusion_unmarked":
        return selected_text or "Reader removed confusion mark."
    if event_type == "reader_settings_changed":
        return json_dumps(payload)
    return selected_text


def _evidence_title(signal: ReaderLearningSignal) -> str:
    titles = {
        "reader_note_insight": "Reader note",
        "reader_confusion_point": "Reader confusion point",
        "reader_explanation_need": "Reader explanation need",
        "reader_example_preference": "Reader example preference",
        "reader_figure_or_table_need": "Reader figure or table need",
    }
    return f"{titles.get(signal.signal_type, 'Reader feedback')} on {signal.paper_id}"


def _target_type(signal: ReaderLearningSignal) -> str:
    return _text(signal.target.get("targetType")) or "reader_selection"


def _target_id(signal: ReaderLearningSignal) -> str:
    return (
        _text(signal.target.get("blockId"))
        or _text(signal.target.get("paragraphId"))
        or _text(signal.target.get("sectionId"))
        or signal.selection_id
        or signal.paper_id
    )


def _run_id(signal: ReaderLearningSignal) -> str:
    return f"paper-reader-feedback:{signal.paper_id}"


def _source_urls(event: Mapping[str, Any]) -> list[str]:
    payload = _mapping(event.get("payload"))
    url = _text(payload.get("sourceUrl") or payload.get("url"))
    return [url] if url else []


def _event_time(event: Mapping[str, Any]) -> datetime:
    value = event.get("createdAt") or event.get("created_at")
    if value:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = _text(value)
        if text:
            return text
    return None


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


__all__ = [
    "HIGH_VALUE_READER_EVENT_TYPES",
    "PaperReaderFeedbackService",
    "ReaderFeedbackIngestionResult",
    "ReaderLearningSignal",
]
