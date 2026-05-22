from __future__ import annotations

from typing import Any, Protocol

from business.memory.intelligence_models import (
    ClaimMemory,
    DecisionMemory,
    EntityMemory,
    EventMemory,
    EvidenceMemory,
    IntelligenceMemoryBundle,
    PreferenceMemory,
)
from infrastructure.storage.vector import VectorDocument


EVIDENCE_ITEMS_COLLECTION = "evidence_items"
CLAIMS_COLLECTION = "claims"
ENTITIES_COLLECTION = "entities"
EVENTS_COLLECTION = "events"
DECISIONS_COLLECTION = "decisions"
PREFERENCES_COLLECTION = "preferences"


class VectorDocumentStore(Protocol):
    def upsert_documents(self, docs: list[VectorDocument]) -> None: ...


class IntelligenceVectorIndexAdapter:
    def __init__(self, vector_store: VectorDocumentStore) -> None:
        self.vector_store = vector_store

    def index_bundle(self, bundle: IntelligenceMemoryBundle) -> tuple[int, list[str], list[str]]:
        docs = _documents_from_bundle(bundle)
        if docs:
            self.vector_store.upsert_documents(docs)
        return len(docs), sorted({doc.collection for doc in docs}), [doc.document_id for doc in docs]


def _documents_from_bundle(bundle: IntelligenceMemoryBundle) -> list[VectorDocument]:
    docs: list[VectorDocument] = []
    docs.extend(_evidence_document(item, bundle=bundle) for item in bundle.evidence)
    docs.extend(_claim_document(item, bundle=bundle) for item in bundle.claims)
    docs.extend(_entity_document(item, bundle=bundle) for item in bundle.entities)
    docs.extend(_event_document(item, bundle=bundle) for item in bundle.events)
    docs.extend(_decision_document(item, bundle=bundle) for item in bundle.decisions)
    docs.extend(_preference_document(item, bundle=bundle) for item in bundle.preferences)
    return docs


def _evidence_document(item: EvidenceMemory, *, bundle: IntelligenceMemoryBundle) -> VectorDocument:
    payload = _payload(item, memory_layer="evidence", object_id=item.evidence_id, bundle=bundle)
    return VectorDocument(
        document_id=item.evidence_id,
        collection=EVIDENCE_ITEMS_COLLECTION,
        text=item.to_index_text(),
        payload=payload,
        source_type="intelligence_evidence",
        run_id=item.run_id,
        evidence_id=item.evidence_id,
        source_item_id=item.source_item_ids[0] if item.source_item_ids else None,
        topic=item.topic or bundle.topic,
        published_at=item.published_at,
    )


def _claim_document(item: ClaimMemory, *, bundle: IntelligenceMemoryBundle) -> VectorDocument:
    payload = _payload(item, memory_layer="claim", object_id=item.claim_id, bundle=bundle)
    return VectorDocument(
        document_id=item.claim_id,
        collection=CLAIMS_COLLECTION,
        text=item.to_index_text(),
        payload=payload,
        source_type="intelligence_claim",
        run_id=item.run_id,
        topic=bundle.topic,
        published_at=item.valid_at or item.first_seen_at,
    )


def _entity_document(item: EntityMemory, *, bundle: IntelligenceMemoryBundle) -> VectorDocument:
    payload = _payload(item, memory_layer="entity", object_id=item.entity_id, bundle=bundle)
    return VectorDocument(
        document_id=item.entity_id,
        collection=ENTITIES_COLLECTION,
        text=item.to_index_text(),
        payload=payload,
        source_type="intelligence_entity",
        run_id=bundle.run_id,
        topic=bundle.topic,
        published_at=item.first_seen_at,
    )


def _event_document(item: EventMemory, *, bundle: IntelligenceMemoryBundle) -> VectorDocument:
    payload = _payload(item, memory_layer="event", object_id=item.event_id, bundle=bundle)
    return VectorDocument(
        document_id=item.event_id,
        collection=EVENTS_COLLECTION,
        text=item.to_index_text(),
        payload=payload,
        source_type="intelligence_event",
        run_id=item.run_id,
        topic=item.topic or bundle.topic,
        published_at=item.event_time or item.detected_at,
    )


def _decision_document(item: DecisionMemory, *, bundle: IntelligenceMemoryBundle) -> VectorDocument:
    payload = _payload(item, memory_layer="decision", object_id=item.decision_id, bundle=bundle)
    return VectorDocument(
        document_id=item.decision_id,
        collection=DECISIONS_COLLECTION,
        text=item.to_index_text(),
        payload=payload,
        source_type="intelligence_decision",
        run_id=item.run_id,
        topic=bundle.topic,
        published_at=item.created_at,
    )


def _preference_document(item: PreferenceMemory, *, bundle: IntelligenceMemoryBundle) -> VectorDocument:
    payload = _payload(item, memory_layer="preference", object_id=item.preference_id, bundle=bundle)
    return VectorDocument(
        document_id=item.preference_id,
        collection=PREFERENCES_COLLECTION,
        text=item.to_index_text(),
        payload=payload,
        source_type="intelligence_preference",
        run_id=bundle.run_id,
        topic=bundle.topic,
        published_at=item.updated_at or item.created_at,
    )


def _payload(
    item: Any,
    *,
    memory_layer: str,
    object_id: str,
    bundle: IntelligenceMemoryBundle,
) -> dict[str, Any]:
    payload = dict(item.to_payload())
    payload.update(
        {
            "memory_layer": memory_layer,
            "memory_object_id": object_id,
            "run_id": payload.get("run_id") or bundle.run_id,
            "topic": payload.get("topic") or bundle.topic,
            "refs": {
                **dict(payload.get("refs") or {}),
                "run_id": payload.get("run_id") or bundle.run_id,
                "memory_layer": memory_layer,
                "memory_object_id": object_id,
            },
        }
    )
    payload.setdefault(f"{memory_layer}_id", object_id)
    return payload


__all__ = [
    "CLAIMS_COLLECTION",
    "DECISIONS_COLLECTION",
    "ENTITIES_COLLECTION",
    "EVENTS_COLLECTION",
    "EVIDENCE_ITEMS_COLLECTION",
    "IntelligenceVectorIndexAdapter",
    "PREFERENCES_COLLECTION",
]
