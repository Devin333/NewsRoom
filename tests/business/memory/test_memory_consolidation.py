from business.memory.consolidation import MemoryConsolidationService, MemoryConsolidationTask
from business.memory.intelligence_models import ClaimMemory, EntityMemory, EventMemory, EvidenceMemory


def test_memory_consolidation_refreshes_claim_status_in_dry_run() -> None:
    service = MemoryConsolidationService(_ConsolidationRepository())

    result = service.run_task(MemoryConsolidationTask(task_type="claim_status_refresh", topic="AI"))

    assert result.changed == 1
    assert result.changes[0]["new_status"] == "contradicted"


def test_memory_consolidation_detects_duplicate_events() -> None:
    service = MemoryConsolidationService(_ConsolidationRepository())

    result = service.run_task(MemoryConsolidationTask(task_type="event_dedupe", topic="AI"))

    assert result.changed == 1
    assert result.changes[0]["action"] == "mark_duplicate_event"


class _ConsolidationRepository:
    entity = EntityMemory(entity_id="entity-1", entity_type="organization", canonical_name="OpenAI")
    claim = ClaimMemory(
        claim_id="claim-1",
        run_id="run-1",
        text="Claim",
        contradicted_by=["ev-2"],
        evidence_ids=["ev-1"],
    )
    event = EventMemory(event_id="event-1", event_type="general_news", title="Event", summary="Summary", run_id="run-1", topic="AI")
    duplicate = EventMemory(event_id="event-2", event_type="general_news", title="Event", summary="Summary", run_id="run-2", topic="AI")

    def get_entity(self, entity_id):
        return self.entity

    def search_entities(self, *, query, limit=100):
        return [self.entity]

    def list_claims_by_topic(self, topic, *, limit=100):
        return [self.claim]

    def list_claims_by_entity(self, entity_id, *, limit=100):
        return [self.claim]

    def search_claims(self, *, query, limit=100):
        return [self.claim]

    def update_claim_status(self, *args, **kwargs):
        raise AssertionError("dry-run must not mutate")

    def list_events_by_topic(self, topic, *, limit=100):
        return [self.event]

    def list_events_by_entity(self, entity_id, *, limit=100):
        return [self.event]

    def search_events(self, *, query, limit=100):
        return [self.event]

    def find_similar_events(self, event, *, limit=100):
        return [self.duplicate] if event.event_id == "event-1" else []

    def search_evidence(self, *, query, topic=None, limit=100):
        return [
            EvidenceMemory(
                evidence_id="ev-1",
                run_id="run-1",
                title="Evidence",
                summary="Summary",
                source_urls=[],
                source_item_ids=[],
                confidence=0.1,
            )
        ]

    def list_evidence_for_claim(self, claim_id):
        return []

    def list_decisions_for_target(self, target_type, target_id, *, limit=100):
        return []
