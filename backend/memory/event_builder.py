from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone as _tz
UTC = _tz.utc
from typing import Any, cast

from backend.memory.intelligence_builder import normalize_text_key, stable_id
from backend.memory.intelligence_models import ClaimMemory, EntityMemory, EventMemory, EvidenceMemory, utc_now


KEYWORD_EVENT_TYPE_RULES = {
    "model_release": ["released", "release", "launch", "model", "weights", "checkpoint"],
    "paper_release": ["paper", "arxiv", "study", "benchmark"],
    "github_trending": ["github", "stars", "repository", "repo"],
    "policy_update": ["policy", "regulation", "law", "act"],
    "funding": ["funding", "raised", "series a", "investment"],
    "acquisition": ["acquired", "acquisition", "merger"],
    "security_issue": ["vulnerability", "cve", "security"],
}


@dataclass(frozen=True)
class EventBuildCandidate:
    event_type: str
    title: str
    summary: str
    claims: list[ClaimMemory]
    evidence: list[EvidenceMemory]
    entities: list[EntityMemory]
    topic: str | None = None
    event_time: datetime | None = None


@dataclass(frozen=True)
class EventBuildResult:
    events: list[EventMemory]
    duplicate_event_ids: list[str] = field(default_factory=list)
    skipped_candidates: list[dict[str, Any]] = field(default_factory=list)


class EventBuilder:
    def __init__(
        self,
        *,
        duplicate_window_days: int = 3,
    ) -> None:
        self.duplicate_window_days = duplicate_window_days

    def build_events(
        self,
        *,
        run_id: str,
        topic: str | None,
        evidence: list[EvidenceMemory],
        claims: list[ClaimMemory],
        entities: list[EntityMemory],
        existing_events: list[EventMemory] | None = None,
    ) -> EventBuildResult:
        existing = list(existing_events or [])
        events: list[EventMemory] = []
        duplicates: list[str] = []
        skipped: list[dict[str, Any]] = []
        for candidate in self.build_candidates(topic=topic, evidence=evidence, claims=claims, entities=entities):
            duplicate = next((event for event in existing if self.is_duplicate_event(candidate, event)), None)
            if duplicate is not None:
                duplicates.append(duplicate.event_id)
                skipped.append({"reason": "duplicate_event", "event_id": duplicate.event_id, "title": candidate.title})
                continue
            event = self.candidate_to_event(candidate, run_id=run_id, existing_events=existing)
            events.append(event)
            existing.append(event)
        return EventBuildResult(events=events, duplicate_event_ids=duplicates, skipped_candidates=skipped)

    def build_candidates(
        self,
        *,
        topic: str | None,
        evidence: list[EvidenceMemory],
        claims: list[ClaimMemory],
        entities: list[EntityMemory],
    ) -> list[EventBuildCandidate]:
        if not evidence and not claims:
            return []
        title = _event_title(topic=topic, evidence=evidence, claims=claims)
        summary = _event_summary(evidence=evidence, claims=claims)
        candidate = EventBuildCandidate(
            event_type="general_news",
            title=title,
            summary=summary,
            claims=list(claims),
            evidence=list(evidence),
            entities=list(entities),
            topic=topic,
            event_time=_best_event_time(evidence),
        )
        return [
            EventBuildCandidate(
                event_type=self.infer_event_type(candidate),
                title=candidate.title,
                summary=candidate.summary,
                claims=candidate.claims,
                evidence=candidate.evidence,
                entities=candidate.entities,
                topic=candidate.topic,
                event_time=candidate.event_time,
            )
        ]

    def infer_event_type(
        self,
        candidate: EventBuildCandidate,
    ) -> str:
        text = normalize_text_key(f"{candidate.title} {candidate.summary}")
        for event_type, keywords in KEYWORD_EVENT_TYPE_RULES.items():
            if any(keyword in text for keyword in keywords):
                return event_type
        return candidate.event_type or "general_news"

    def is_duplicate_event(
        self,
        candidate: EventBuildCandidate,
        existing_event: EventMemory,
    ) -> bool:
        if candidate.topic and existing_event.topic and candidate.topic.casefold() != existing_event.topic.casefold():
            return False
        if candidate.event_type != existing_event.event_type:
            return False
        if normalize_text_key(candidate.title) == normalize_text_key(existing_event.title):
            return self._within_duplicate_window(candidate.event_time, existing_event.event_time or existing_event.detected_at)
        candidate_ids = {claim.claim_id for claim in candidate.claims} | {item.evidence_id for item in candidate.evidence}
        existing_ids = set(existing_event.claim_ids) | set(existing_event.evidence_ids)
        if candidate_ids and candidate_ids & existing_ids:
            return self._within_duplicate_window(candidate.event_time, existing_event.event_time or existing_event.detected_at)
        return False

    def compute_impact_score(
        self,
        candidate: EventBuildCandidate,
    ) -> float:
        score = 0.15
        score += min(0.30, len(candidate.evidence) * 0.05)
        score += min(0.25, len(candidate.claims) * 0.05)
        score += min(0.20, len(candidate.entities) * 0.04)
        return _clamp(score)

    def compute_novelty_score(
        self,
        candidate: EventBuildCandidate,
        existing_events: list[EventMemory],
    ) -> float:
        if not existing_events:
            return 1.0
        duplicates = [event for event in existing_events if self.is_duplicate_event(candidate, event)]
        if duplicates:
            return 0.1
        same_topic = [
            event
            for event in existing_events
            if candidate.topic and event.topic and candidate.topic.casefold() == event.topic.casefold()
        ]
        if same_topic:
            return 0.6
        return 0.9

    def candidate_to_event(
        self,
        candidate: EventBuildCandidate,
        *,
        run_id: str,
        existing_events: list[EventMemory],
    ) -> EventMemory:
        return EventMemory(
            event_id=stable_event_id(candidate.event_type, candidate.title, candidate.topic, candidate.event_time),
            event_type=cast(Any, candidate.event_type),
            title=candidate.title,
            summary=candidate.summary,
            run_id=run_id,
            event_time=candidate.event_time,
            detected_at=utc_now(),
            topic=candidate.topic,
            entity_ids=sorted({entity.entity_id for entity in candidate.entities}),
            claim_ids=sorted({claim.claim_id for claim in candidate.claims}),
            evidence_ids=sorted({item.evidence_id for item in candidate.evidence}),
            impact_score=self.compute_impact_score(candidate),
            novelty_score=self.compute_novelty_score(candidate, existing_events),
            status="active",
            metadata={"source": "phase2_event_builder"},
        )

    def _within_duplicate_window(self, left: datetime | None, right: datetime | None) -> bool:
        if left is None or right is None:
            return True
        left_utc = _ensure_utc(left)
        right_utc = _ensure_utc(right)
        return abs(left_utc - right_utc) <= timedelta(days=self.duplicate_window_days)


def stable_event_id(event_type: str, title: str, topic: str | None, event_time: datetime | None) -> str:
    date_bucket = _ensure_utc(event_time).date().isoformat() if event_time else "unknown-date"
    return stable_id("event", event_type, topic or "", date_bucket, normalize_text_key(title), prefix="event")


def _event_title(*, topic: str | None, evidence: list[EvidenceMemory], claims: list[ClaimMemory]) -> str:
    if evidence and evidence[0].title.strip():
        return evidence[0].title.strip()
    if claims and claims[0].text.strip():
        text = claims[0].text.strip()
        return text[:120]
    return f"Agora Hub update for {topic or 'run'}"


def _event_summary(*, evidence: list[EvidenceMemory], claims: list[ClaimMemory]) -> str:
    claim_text = " ".join(claim.text.strip() for claim in claims[:3] if claim.text.strip())
    if claim_text:
        return claim_text
    return " ".join((item.summary or item.title).strip() for item in evidence[:3] if (item.summary or item.title).strip())


def _best_event_time(evidence: list[EvidenceMemory]) -> datetime | None:
    dates = [item.published_at for item in evidence if item.published_at is not None]
    if dates:
        return max(_ensure_utc(item) for item in dates)
    fetched = [item.fetched_at for item in evidence if item.fetched_at is not None]
    if fetched:
        return max(_ensure_utc(item) for item in fetched)
    return None


def _ensure_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


__all__ = [
    "EventBuildCandidate",
    "EventBuildResult",
    "EventBuilder",
    "KEYWORD_EVENT_TYPE_RULES",
    "stable_event_id",
]
