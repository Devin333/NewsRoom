from __future__ import annotations

from typing import Any, Protocol

from backend.memory.intelligence_models import (
    ClaimHistoryRecord,
    ClaimMemory,
    DecisionMemory,
    EntityMemory,
    EventMemory,
    EvidenceMemory,
    PreferenceMemory,
)


class IntelligenceMemoryRepository(Protocol):
    def save_evidence(self, items: list[EvidenceMemory]) -> None: ...

    def save_claims(self, claims: list[ClaimMemory]) -> None: ...

    def save_entities(self, entities: list[EntityMemory]) -> None: ...

    def save_events(self, events: list[EventMemory]) -> None: ...

    def save_decisions(self, decisions: list[DecisionMemory]) -> None: ...

    def save_preferences(self, preferences: list[PreferenceMemory]) -> None: ...


class IntelligenceMemoryQueryRepository(Protocol):
    def search_evidence(self, *, query: str, topic: str | None = None, limit: int = 8) -> list[EvidenceMemory]: ...

    def search_claims(self, *, query: str, topic: str | None = None, limit: int = 8) -> list[ClaimMemory]: ...

    def search_entities(self, *, query: str, topic: str | None = None, limit: int = 8) -> list[EntityMemory]: ...

    def search_events(self, *, query: str, topic: str | None = None, limit: int = 8) -> list[EventMemory]: ...

    def search_decisions(self, *, query: str, topic: str | None = None, limit: int = 8) -> list[DecisionMemory]: ...

    def search_preferences(self, *, query: str, topic: str | None = None, limit: int = 8) -> list[PreferenceMemory]: ...

    def get_entity(self, entity_id: str) -> EntityMemory | None: ...

    def find_entity_by_name(self, name: str) -> EntityMemory | None: ...

    def list_entities_by_type(self, entity_type: str, *, limit: int = 20) -> list[EntityMemory]: ...

    def get_claim(self, claim_id: str) -> ClaimMemory | None: ...

    def find_similar_claims(self, claim: ClaimMemory, *, limit: int = 10) -> list[ClaimMemory]: ...

    def list_claims_by_entity(self, entity_id: str, *, limit: int = 20) -> list[ClaimMemory]: ...

    def list_claims_by_topic(self, topic: str, *, limit: int = 20) -> list[ClaimMemory]: ...

    def list_evidence_for_claim(self, claim_id: str) -> list[EvidenceMemory]: ...

    def get_event(self, event_id: str) -> EventMemory | None: ...

    def find_similar_events(self, event: EventMemory, *, limit: int = 10) -> list[EventMemory]: ...

    def list_events_by_entity(self, entity_id: str, *, limit: int = 20) -> list[EventMemory]: ...

    def list_events_by_topic(self, topic: str, *, limit: int = 20) -> list[EventMemory]: ...

    def list_decisions_for_target(
        self,
        target_type: str,
        target_id: str,
        *,
        limit: int = 20,
    ) -> list[DecisionMemory]: ...

    def list_preferences(
        self,
        *,
        owner_type: str,
        owner_id: str,
        preference_type: str | None = None,
        limit: int = 20,
    ) -> list[PreferenceMemory]: ...


class IntelligenceMemoryMutationRepository(IntelligenceMemoryRepository, Protocol):
    def upsert_entity(self, entity: EntityMemory) -> None: ...

    def upsert_claim(self, claim: ClaimMemory) -> None: ...

    def update_claim_status(
        self,
        claim_id: str,
        *,
        status: str,
        confidence: float | None = None,
        reason: str | None = None,
        evidence_id: str | None = None,
    ) -> None: ...

    def upsert_event(self, event: EventMemory) -> None: ...

    def link_event_entity(self, event_id: str, entity_id: str, *, role: str = "mentioned") -> None: ...

    def link_event_claim(self, event_id: str, claim_id: str, *, role: str = "supporting") -> None: ...

    def link_event_evidence(self, event_id: str, evidence_id: str, *, support_type: str = "supporting") -> None: ...

    def append_claim_history(self, history: ClaimHistoryRecord) -> None: ...


class IntelligenceMemoryVectorIndex(Protocol):
    def index_bundle(self, bundle: Any) -> tuple[int, list[str], list[str]]: ...


__all__ = [
    "IntelligenceMemoryMutationRepository",
    "IntelligenceMemoryQueryRepository",
    "IntelligenceMemoryRepository",
    "IntelligenceMemoryVectorIndex",
]
