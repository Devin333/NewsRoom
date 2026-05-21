from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from business.memory.intelligence_models import (
    ClaimMemory,
    DecisionMemory,
    EntityMemory,
    EventMemory,
    EvidenceMemory,
    PreferenceMemory,
)


@dataclass(frozen=True)
class IntelligenceMemoryContext:
    query: str
    topic: str | None = None
    evidence: list[EvidenceMemory] = field(default_factory=list)
    claims: list[ClaimMemory] = field(default_factory=list)
    entities: list[EntityMemory] = field(default_factory=list)
    events: list[EventMemory] = field(default_factory=list)
    decisions: list[DecisionMemory] = field(default_factory=list)
    preferences: list[PreferenceMemory] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not any(
            [
                self.evidence,
                self.claims,
                self.entities,
                self.events,
                self.decisions,
                self.preferences,
                self.conflicts,
            ]
        )

    def to_prompt_context(self, *, limit: int = 10) -> str:
        sections: list[str] = []
        if self.claims:
            sections.append("Known claims:\n" + "\n".join(f"- {item.text}" for item in self.claims[:limit]))
        if self.events:
            sections.append(
                "Recent timeline:\n"
                + "\n".join(
                    f"- {(item.event_time or item.detected_at).date().isoformat()} [{item.event_type}] {item.title}: {item.summary}"
                    for item in self.events[:limit]
                )
            )
        if self.evidence:
            sections.append(
                "Supporting evidence:\n"
                + "\n".join(f"- {item.title}: {item.summary}" for item in self.evidence[:limit])
            )
        if self.entities:
            sections.append(
                "Entity profiles:\n"
                + "\n".join(f"- {item.canonical_name} ({item.entity_type})" for item in self.entities[:limit])
            )
        if self.decisions:
            sections.append(
                "Previous decisions:\n"
                + "\n".join(f"- {item.decision_type}: {item.decision}" for item in self.decisions[:limit])
            )
        if self.preferences:
            sections.append(
                "Preferences:\n"
                + "\n".join(f"- {item.preference_type}: {item.content}" for item in self.preferences[:limit])
            )
        if self.conflicts:
            sections.append(
                "Conflicts / warnings:\n"
                + "\n".join(f"- {item.get('message') or item.get('issue_type') or item}" for item in self.conflicts[:limit])
            )
        return "\n\n".join(sections)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "topic": self.topic,
            "evidence": [item.to_payload() for item in self.evidence],
            "claims": [item.to_payload() for item in self.claims],
            "entities": [item.to_payload() for item in self.entities],
            "events": [item.to_payload() for item in self.events],
            "decisions": [item.to_payload() for item in self.decisions],
            "preferences": [item.to_payload() for item in self.preferences],
            "conflicts": [dict(item) for item in self.conflicts],
            "metadata": dict(self.metadata),
        }


__all__ = ["IntelligenceMemoryContext"]
