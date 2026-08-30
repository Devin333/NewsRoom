from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from typing import Any

from backend.memory.intelligence_models import (
    ClaimHistoryRecord,
    ClaimMemory,
    DecisionMemory,
    EntityMemory,
    EventMemory,
    EvidenceMemory,
    PreferenceMemory,
)
from backend.memory.intelligence_builder import stable_id
from infrastructure.storage.postgres.repository import PostgresRepository
from infrastructure.storage.records import ClaimRecord, EvidenceItemRecord


class PostgresIntelligenceMemoryRepository:
    def __init__(self, repository: PostgresRepository) -> None:
        self.repository = repository

    def save_evidence(self, items: list[EvidenceMemory]) -> None:
        for item in items:
            self.repository.save_evidence_item(
                EvidenceItemRecord(
                    evidence_id=item.evidence_id,
                    run_id=item.run_id,
                    claim=item.title,
                    summary=item.summary,
                    source_urls=item.normalized_source_urls(),
                    source_item_ids=list(item.source_item_ids),
                    confidence=item.confidence,
                    category=item.category,
                    published_at=item.published_at,
                    lineage_json={
                        "source_name": item.source_name,
                        "source_id": item.source_id,
                        "raw_artifact_ref": item.raw_artifact_ref,
                    },
                    metadata=item.to_payload(),
                )
            )

    def save_claims(self, claims: list[ClaimMemory]) -> None:
        for claim in claims:
            self.repository.save_claim(
                ClaimRecord(
                    claim_id=claim.claim_id,
                    run_id=claim.run_id,
                    status=claim.status,
                    text=claim.text,
                    confidence=claim.confidence,
                    supporting_evidence_ids=list(claim.evidence_ids),
                    rejecting_evidence_ids=list(claim.contradicted_by),
                    payload=claim.to_payload(),
                    created_at=claim.first_seen_at,
                )
            )

    def save_entities(self, entities: list[EntityMemory]) -> None:
        for entity in entities:
            self.repository.execute(
                """
                INSERT INTO memory_entities (
                    entity_id, entity_type, canonical_name, aliases, summary,
                    first_seen_at, last_seen_at, importance_score, trend_score,
                    external_refs, metadata_json
                )
                VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                ON CONFLICT (entity_id) DO UPDATE SET
                    entity_type = EXCLUDED.entity_type,
                    canonical_name = EXCLUDED.canonical_name,
                    aliases = EXCLUDED.aliases,
                    summary = EXCLUDED.summary,
                    last_seen_at = EXCLUDED.last_seen_at,
                    importance_score = EXCLUDED.importance_score,
                    trend_score = EXCLUDED.trend_score,
                    external_refs = EXCLUDED.external_refs,
                    metadata_json = EXCLUDED.metadata_json,
                    updated_at = now()
                """,
                (
                    entity.entity_id,
                    entity.entity_type,
                    entity.canonical_name,
                    _json_list(entity.aliases),
                    entity.summary,
                    entity.first_seen_at,
                    entity.last_seen_at,
                    entity.importance_score,
                    entity.trend_score,
                    _json(entity.external_refs),
                    _json(entity.metadata),
                ),
            )

    def save_events(self, events: list[EventMemory]) -> None:
        for event in events:
            self.repository.execute(
                """
                INSERT INTO memory_events (
                    event_id, event_type, title, summary, run_id, event_time,
                    detected_at, topic, impact_score, novelty_score, status, metadata_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (event_id) DO UPDATE SET
                    event_type = EXCLUDED.event_type,
                    title = EXCLUDED.title,
                    summary = EXCLUDED.summary,
                    run_id = EXCLUDED.run_id,
                    event_time = EXCLUDED.event_time,
                    detected_at = EXCLUDED.detected_at,
                    topic = EXCLUDED.topic,
                    impact_score = EXCLUDED.impact_score,
                    novelty_score = EXCLUDED.novelty_score,
                    status = EXCLUDED.status,
                    metadata_json = EXCLUDED.metadata_json,
                    updated_at = now()
                """,
                (
                    event.event_id,
                    event.event_type,
                    event.title,
                    event.summary,
                    event.run_id,
                    event.event_time,
                    event.detected_at,
                    event.topic,
                    event.impact_score,
                    event.novelty_score,
                    event.status,
                    _json(event.metadata),
                ),
            )
            self._refresh_event_refs(
                event.event_id,
                "memory_event_entities",
                "entity_id",
                event.entity_ids,
                role_column="role",
                role_value="mentioned",
            )
            self._refresh_event_refs(
                event.event_id,
                "memory_event_claims",
                "claim_id",
                event.claim_ids,
                role_column="role",
                role_value="supporting",
            )
            self._refresh_event_refs(
                event.event_id,
                "memory_event_evidence",
                "evidence_id",
                event.evidence_ids,
                role_column="support_type",
                role_value="supporting",
            )

    def save_decisions(self, decisions: list[DecisionMemory]) -> None:
        for decision in decisions:
            self.repository.execute(
                """
                INSERT INTO memory_decisions (
                    decision_id, decision_type, target_type, target_id, decision,
                    reason, run_id, graph_id, graph_version, graph_ref, graph_checksum, agent_id, input_features,
                    output_scores, metadata_json, created_at
                )
                VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s::jsonb, %s::jsonb, %s
                )
                ON CONFLICT (decision_id) DO UPDATE SET
                    decision_type = EXCLUDED.decision_type,
                    target_type = EXCLUDED.target_type,
                    target_id = EXCLUDED.target_id,
                    decision = EXCLUDED.decision,
                    reason = EXCLUDED.reason,
                    run_id = EXCLUDED.run_id,
                    graph_id = EXCLUDED.graph_id,
                    graph_version = EXCLUDED.graph_version,
                    graph_ref = EXCLUDED.graph_ref,
                    graph_checksum = EXCLUDED.graph_checksum,
                    agent_id = EXCLUDED.agent_id,
                    input_features = EXCLUDED.input_features,
                    output_scores = EXCLUDED.output_scores,
                    metadata_json = EXCLUDED.metadata_json,
                    updated_at = now()
                """,
                (
                    decision.decision_id,
                    decision.decision_type,
                    decision.target_type,
                    decision.target_id,
                    decision.decision,
                    decision.reason,
                    decision.run_id,
                    decision.graph_id,
                    decision.graph_version,
                    decision.graph_ref,
                    decision.graph_checksum,
                    decision.agent_id,
                    _json(decision.input_features),
                    _json(decision.output_scores),
                    _json(decision.metadata),
                    decision.created_at,
                ),
            )

    def save_preferences(self, preferences: list[PreferenceMemory]) -> None:
        for preference in preferences:
            self.repository.execute(
                """
                INSERT INTO memory_preferences (
                    preference_id, owner_type, owner_id, preference_type, content,
                    weight, source, created_at, updated_at, expires_at, metadata_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (preference_id) DO UPDATE SET
                    owner_type = EXCLUDED.owner_type,
                    owner_id = EXCLUDED.owner_id,
                    preference_type = EXCLUDED.preference_type,
                    content = EXCLUDED.content,
                    weight = EXCLUDED.weight,
                    source = EXCLUDED.source,
                    updated_at = EXCLUDED.updated_at,
                    expires_at = EXCLUDED.expires_at,
                    metadata_json = EXCLUDED.metadata_json
                """,
                (
                    preference.preference_id,
                    preference.owner_type,
                    preference.owner_id,
                    preference.preference_type,
                    preference.content,
                    preference.weight,
                    preference.source,
                    preference.created_at,
                    preference.updated_at,
                    preference.expires_at,
                    _json(preference.metadata),
                ),
            )

    def upsert_entity(self, entity: EntityMemory) -> None:
        self.save_entities([entity])

    def upsert_claim(self, claim: ClaimMemory) -> None:
        self.save_claims([claim])

    def update_claim_status(
        self,
        claim_id: str,
        *,
        status: str,
        confidence: float | None = None,
        reason: str | None = None,
        evidence_id: str | None = None,
    ) -> None:
        old_claim = self.get_claim(claim_id)
        if old_claim is None:
            self.repository.execute(
                """
                UPDATE claims
                SET status = %s,
                    payload = jsonb_set(COALESCE(payload, '{}'::jsonb), '{status}', to_jsonb(%s::text), true),
                    updated_at = now()
                WHERE claim_id = %s
                """,
                (status, status, claim_id),
            )
            return

        new_confidence = confidence if confidence is not None else old_claim.confidence
        metadata = dict(old_claim.metadata)
        if reason:
            metadata["status_update_reason"] = reason
        contradicted_by = list(old_claim.contradicted_by)
        if status == "contradicted" and evidence_id:
            contradicted_by = sorted({*contradicted_by, evidence_id})
        updated = replace(
            old_claim,
            status=status,  # type: ignore[arg-type]
            confidence=new_confidence,
            contradicted_by=contradicted_by,
            metadata=metadata,
        )
        self.save_claims([updated])
        self.append_claim_history(
            ClaimHistoryRecord(
                history_id=stable_id(
                    "claim-history",
                    claim_id,
                    old_claim.status,
                    status,
                    old_claim.confidence,
                    new_confidence,
                    evidence_id,
                    prefix="claim-history",
                ),
                claim_id=claim_id,
                old_status=old_claim.status,
                new_status=status,
                old_confidence=old_claim.confidence,
                new_confidence=new_confidence,
                reason=reason,
                evidence_id=evidence_id,
            )
        )

    def upsert_event(self, event: EventMemory) -> None:
        self.save_events([event])

    def link_event_entity(self, event_id: str, entity_id: str, *, role: str = "mentioned") -> None:
        self._insert_event_ref("memory_event_entities", "entity_id", event_id, entity_id, role_column="role", role_value=role)

    def link_event_claim(self, event_id: str, claim_id: str, *, role: str = "supporting") -> None:
        self._insert_event_ref("memory_event_claims", "claim_id", event_id, claim_id, role_column="role", role_value=role)

    def link_event_evidence(self, event_id: str, evidence_id: str, *, support_type: str = "supporting") -> None:
        self._insert_event_ref(
            "memory_event_evidence",
            "evidence_id",
            event_id,
            evidence_id,
            role_column="support_type",
            role_value=support_type,
        )

    def append_claim_history(self, history: ClaimHistoryRecord) -> None:
        self.repository.execute(
            """
            INSERT INTO memory_claim_history (
                history_id, claim_id, old_status, new_status,
                old_confidence, new_confidence, reason, evidence_id,
                created_at, metadata_json
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (history_id) DO UPDATE SET
                claim_id = EXCLUDED.claim_id,
                old_status = EXCLUDED.old_status,
                new_status = EXCLUDED.new_status,
                old_confidence = EXCLUDED.old_confidence,
                new_confidence = EXCLUDED.new_confidence,
                reason = EXCLUDED.reason,
                evidence_id = EXCLUDED.evidence_id,
                metadata_json = EXCLUDED.metadata_json
            """,
            (
                history.history_id,
                history.claim_id,
                history.old_status,
                history.new_status,
                history.old_confidence,
                history.new_confidence,
                history.reason,
                history.evidence_id,
                history.created_at,
                _json(history.metadata),
            ),
        )

    def search_evidence(self, *, query: str, topic: str | None = None, limit: int = 8) -> list[EvidenceMemory]:
        where = ["(COALESCE(title, '') ILIKE %s OR COALESCE(summary, '') ILIKE %s OR payload::text ILIKE %s)"]
        pattern = _pattern(query)
        params: list[Any] = [pattern, pattern, pattern]
        if topic:
            where.append("payload::text ILIKE %s")
            params.append(_pattern(topic))
        params.append(_limit(limit))
        rows = self.repository.fetch_all(
            f"""
            SELECT payload
            FROM evidence_items
            WHERE {' AND '.join(where)}
            ORDER BY published_at DESC NULLS LAST, updated_at DESC
            LIMIT %s
            """,
            tuple(params),
        )
        return [_evidence_from_payload(row[0]) for row in rows]

    def search_claims(self, *, query: str, topic: str | None = None, limit: int = 8) -> list[ClaimMemory]:
        where = ["(COALESCE(text, '') ILIKE %s OR payload::text ILIKE %s)"]
        params: list[Any] = [_pattern(query), _pattern(query)]
        if topic:
            where.append("payload::text ILIKE %s")
            params.append(_pattern(topic))
        params.append(_limit(limit))
        rows = self.repository.fetch_all(
            f"""
            SELECT payload
            FROM claims
            WHERE {' AND '.join(where)}
            ORDER BY updated_at DESC
            LIMIT %s
            """,
            tuple(params),
        )
        return [_claim_from_payload(row[0]) for row in rows]

    def search_entities(self, *, query: str, topic: str | None = None, limit: int = 8) -> list[EntityMemory]:
        del topic
        rows = self.repository.fetch_all(
            """
            SELECT
                entity_id, entity_type, canonical_name, aliases, summary,
                first_seen_at, last_seen_at, importance_score, trend_score,
                external_refs, metadata_json
            FROM memory_entities
            WHERE
                COALESCE(canonical_name, '') ILIKE %s
                OR COALESCE(summary, '') ILIKE %s
                OR aliases::text ILIKE %s
                OR metadata_json::text ILIKE %s
            ORDER BY importance_score DESC, last_seen_at DESC
            LIMIT %s
            """,
            (_pattern(query), _pattern(query), _pattern(query), _pattern(query), _limit(limit)),
        )
        return [_entity_from_row(row) for row in rows]

    def search_events(self, *, query: str, topic: str | None = None, limit: int = 8) -> list[EventMemory]:
        where = ["(COALESCE(e.title, '') ILIKE %s OR COALESCE(e.summary, '') ILIKE %s OR e.metadata_json::text ILIKE %s)"]
        params: list[Any] = [_pattern(query), _pattern(query), _pattern(query)]
        if topic:
            where.append("e.topic = %s")
            params.append(topic)
        params.append(_limit(limit))
        rows = self.repository.fetch_all(
            f"""
            {_EVENT_SELECT}
            FROM memory_events e
            WHERE {' AND '.join(where)}
            ORDER BY COALESCE(e.event_time, e.detected_at) DESC
            LIMIT %s
            """,
            tuple(params),
        )
        return [_event_from_row(row) for row in rows]

    def search_decisions(self, *, query: str, topic: str | None = None, limit: int = 8) -> list[DecisionMemory]:
        del topic
        rows = self.repository.fetch_all(
            """
            SELECT
                decision_id, decision_type, target_type, target_id, decision,
                reason, run_id, graph_id, graph_version, graph_ref, graph_checksum, agent_id, input_features,
                output_scores, created_at, metadata_json
            FROM memory_decisions
            WHERE
                COALESCE(decision_type, '') ILIKE %s
                OR COALESCE(decision, '') ILIKE %s
                OR COALESCE(reason, '') ILIKE %s
                OR metadata_json::text ILIKE %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (_pattern(query), _pattern(query), _pattern(query), _pattern(query), _limit(limit)),
        )
        return [_decision_from_row(row) for row in rows]

    def search_preferences(self, *, query: str, topic: str | None = None, limit: int = 8) -> list[PreferenceMemory]:
        del topic
        rows = self.repository.fetch_all(
            """
            SELECT
                preference_id, owner_type, owner_id, preference_type, content,
                weight, source, created_at, updated_at, expires_at, metadata_json
            FROM memory_preferences
            WHERE
                COALESCE(preference_type, '') ILIKE %s
                OR COALESCE(content, '') ILIKE %s
                OR metadata_json::text ILIKE %s
            ORDER BY COALESCE(updated_at, created_at) DESC
            LIMIT %s
            """,
            (_pattern(query), _pattern(query), _pattern(query), _limit(limit)),
        )
        return [_preference_from_row(row) for row in rows]

    def get_entity(self, entity_id: str) -> EntityMemory | None:
        row = self.repository.fetch_one(
            """
            SELECT
                entity_id, entity_type, canonical_name, aliases, summary,
                first_seen_at, last_seen_at, importance_score, trend_score,
                external_refs, metadata_json
            FROM memory_entities
            WHERE entity_id = %s
            """,
            (entity_id,),
        )
        return _entity_from_row(row) if row is not None else None

    def find_entity_by_name(self, name: str) -> EntityMemory | None:
        row = self.repository.fetch_one(
            """
            SELECT
                entity_id, entity_type, canonical_name, aliases, summary,
                first_seen_at, last_seen_at, importance_score, trend_score,
                external_refs, metadata_json
            FROM memory_entities
            WHERE lower(canonical_name) = lower(%s) OR aliases::text ILIKE %s
            ORDER BY importance_score DESC, last_seen_at DESC
            LIMIT 1
            """,
            (name, _pattern(name)),
        )
        return _entity_from_row(row) if row is not None else None

    def list_entities_by_type(self, entity_type: str, *, limit: int = 20) -> list[EntityMemory]:
        rows = self.repository.fetch_all(
            """
            SELECT
                entity_id, entity_type, canonical_name, aliases, summary,
                first_seen_at, last_seen_at, importance_score, trend_score,
                external_refs, metadata_json
            FROM memory_entities
            WHERE entity_type = %s
            ORDER BY importance_score DESC, last_seen_at DESC
            LIMIT %s
            """,
            (entity_type, _limit(limit)),
        )
        return [_entity_from_row(row) for row in rows]

    def get_claim(self, claim_id: str) -> ClaimMemory | None:
        row = self.repository.fetch_one("SELECT payload FROM claims WHERE claim_id = %s", (claim_id,))
        return _claim_from_payload(row[0]) if row is not None else None

    def find_similar_claims(self, claim: ClaimMemory, *, limit: int = 10) -> list[ClaimMemory]:
        query = claim.text or claim.claim_id
        rows = self.repository.fetch_all(
            """
            SELECT payload
            FROM claims
            WHERE
                claim_id <> %s
                AND (
                    lower(text) = lower(%s)
                    OR payload::text ILIKE %s
                    OR COALESCE(text, '') ILIKE %s
                )
            ORDER BY updated_at DESC
            LIMIT %s
            """,
            (claim.claim_id, query, _pattern(claim.subject_entity_id or query), _pattern(query), _limit(limit)),
        )
        return [_claim_from_payload(row[0]) for row in rows]

    def list_claims_by_entity(self, entity_id: str, *, limit: int = 20) -> list[ClaimMemory]:
        rows = self.repository.fetch_all(
            """
            SELECT payload
            FROM claims
            WHERE payload::text ILIKE %s
            ORDER BY updated_at DESC
            LIMIT %s
            """,
            (_pattern(entity_id), _limit(limit)),
        )
        return [_claim_from_payload(row[0]) for row in rows]

    def list_claims_by_topic(self, topic: str, *, limit: int = 20) -> list[ClaimMemory]:
        rows = self.repository.fetch_all(
            """
            SELECT payload
            FROM claims
            WHERE payload::text ILIKE %s
            ORDER BY updated_at DESC
            LIMIT %s
            """,
            (_pattern(topic), _limit(limit)),
        )
        return [_claim_from_payload(row[0]) for row in rows]

    def list_evidence_for_claim(self, claim_id: str) -> list[EvidenceMemory]:
        rows = self.repository.fetch_all(
            """
            SELECT e.payload
            FROM claim_supports cs
            JOIN evidence_items e ON e.evidence_id = cs.evidence_id
            WHERE cs.claim_id = %s
            ORDER BY e.published_at DESC NULLS LAST, e.updated_at DESC
            """,
            (claim_id,),
        )
        return [_evidence_from_payload(row[0]) for row in rows]

    def get_event(self, event_id: str) -> EventMemory | None:
        row = self.repository.fetch_one(
            f"""
            {_EVENT_SELECT}
            FROM memory_events e
            WHERE e.event_id = %s
            """,
            (event_id,),
        )
        return _event_from_row(row) if row is not None else None

    def find_similar_events(self, event: EventMemory, *, limit: int = 10) -> list[EventMemory]:
        rows = self.repository.fetch_all(
            f"""
            {_EVENT_SELECT}
            FROM memory_events e
            WHERE
                e.event_id <> %s
                AND (
                    e.event_type = %s
                    OR e.topic = %s
                    OR COALESCE(e.title, '') ILIKE %s
                    OR COALESCE(e.summary, '') ILIKE %s
                )
            ORDER BY COALESCE(e.event_time, e.detected_at) DESC
            LIMIT %s
            """,
            (event.event_id, event.event_type, event.topic, _pattern(event.title), _pattern(event.summary), _limit(limit)),
        )
        return [_event_from_row(row) for row in rows]

    def list_events_by_entity(self, entity_id: str, *, limit: int = 20) -> list[EventMemory]:
        rows = self.repository.fetch_all(
            f"""
            {_EVENT_SELECT}
            FROM memory_events e
            JOIN memory_event_entities mee ON mee.event_id = e.event_id
            WHERE mee.entity_id = %s
            ORDER BY COALESCE(e.event_time, e.detected_at) DESC
            LIMIT %s
            """,
            (entity_id, _limit(limit)),
        )
        return [_event_from_row(row) for row in rows]

    def list_events_by_topic(self, topic: str, *, limit: int = 20) -> list[EventMemory]:
        rows = self.repository.fetch_all(
            f"""
            {_EVENT_SELECT}
            FROM memory_events e
            WHERE e.topic = %s
            ORDER BY COALESCE(e.event_time, e.detected_at) DESC
            LIMIT %s
            """,
            (topic, _limit(limit)),
        )
        return [_event_from_row(row) for row in rows]

    def list_decisions_for_target(
        self,
        target_type: str,
        target_id: str,
        *,
        limit: int = 20,
    ) -> list[DecisionMemory]:
        rows = self.repository.fetch_all(
            """
            SELECT
                decision_id, decision_type, target_type, target_id, decision,
                reason, run_id, graph_id, graph_version, graph_ref, graph_checksum, agent_id, input_features,
                output_scores, created_at, metadata_json
            FROM memory_decisions
            WHERE target_type = %s AND target_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (target_type, target_id, _limit(limit)),
        )
        return [_decision_from_row(row) for row in rows]

    def list_preferences(
        self,
        *,
        owner_type: str,
        owner_id: str,
        preference_type: str | None = None,
        limit: int = 20,
    ) -> list[PreferenceMemory]:
        where = ["owner_type = %s", "owner_id = %s"]
        params: list[Any] = [owner_type, owner_id]
        if preference_type:
            where.append("preference_type = %s")
            params.append(preference_type)
        params.append(_limit(limit))
        rows = self.repository.fetch_all(
            f"""
            SELECT
                preference_id, owner_type, owner_id, preference_type, content,
                weight, source, created_at, updated_at, expires_at, metadata_json
            FROM memory_preferences
            WHERE {' AND '.join(where)}
            ORDER BY COALESCE(updated_at, created_at) DESC
            LIMIT %s
            """,
            tuple(params),
        )
        return [_preference_from_row(row) for row in rows]

    def _refresh_event_refs(
        self,
        event_id: str,
        table: str,
        column: str,
        values: list[str],
        *,
        role_column: str,
        role_value: str,
    ) -> None:
        self.repository.execute(f"DELETE FROM {table} WHERE event_id = %s", (event_id,))
        for value in sorted({str(item) for item in values if str(item).strip()}):
            self._insert_event_ref(
                table,
                column,
                event_id,
                value,
                role_column=role_column,
                role_value=role_value,
            )

    def _insert_event_ref(
        self,
        table: str,
        column: str,
        event_id: str,
        value: str,
        *,
        role_column: str,
        role_value: str,
    ) -> None:
        self.repository.execute(
            f"""
            INSERT INTO {table} (event_id, {column}, {role_column})
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (event_id, value, role_value),
        )


_EVENT_SELECT = """
            SELECT
                e.event_id, e.event_type, e.title, e.summary, e.run_id,
                e.event_time, e.detected_at, e.topic, e.impact_score,
                e.novelty_score, e.status, e.metadata_json,
                COALESCE((SELECT json_agg(entity_id) FROM memory_event_entities WHERE event_id = e.event_id), '[]'::json) AS entity_ids,
                COALESCE((SELECT json_agg(claim_id) FROM memory_event_claims WHERE event_id = e.event_id), '[]'::json) AS claim_ids,
                COALESCE((SELECT json_agg(evidence_id) FROM memory_event_evidence WHERE event_id = e.event_id), '[]'::json) AS evidence_ids
"""


def _json(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)


def _json_list(value: Any) -> str:
    return json.dumps(value or [], ensure_ascii=False, sort_keys=True)


def _pattern(value: str | None) -> str:
    return f"%{value or ''}%"


def _limit(value: int) -> int:
    return max(1, int(value or 1))


def _payload(value: Any) -> dict[str, Any]:
    payload = _dict_or_empty(value)
    nested = _dict_or_empty(payload.get("payload"))
    return nested or payload


def _evidence_from_payload(value: Any) -> EvidenceMemory:
    payload = _payload(value)
    metadata = _dict_or_empty(payload.get("metadata"))
    memory_payload = metadata if "evidence_id" in metadata else payload
    return EvidenceMemory(
        evidence_id=str(memory_payload.get("evidence_id") or payload.get("evidence_id") or ""),
        run_id=str(memory_payload.get("run_id") or payload.get("run_id") or ""),
        title=str(memory_payload.get("title") or payload.get("claim") or ""),
        summary=str(memory_payload.get("summary") or ""),
        source_urls=_str_list(memory_payload.get("source_urls") or payload.get("source_urls")),
        source_item_ids=_str_list(memory_payload.get("source_item_ids") or payload.get("source_item_ids")),
        confidence=float(memory_payload.get("confidence") or payload.get("confidence") or 0.5),
        category=str(memory_payload.get("category") or payload.get("category") or "news"),
        published_at=_dt(memory_payload.get("published_at") or payload.get("published_at")),
        fetched_at=_dt(memory_payload.get("fetched_at")),
        topic=memory_payload.get("topic"),
        source_name=memory_payload.get("source_name"),
        source_id=memory_payload.get("source_id"),
        content_hash=memory_payload.get("content_hash"),
        raw_artifact_ref=memory_payload.get("raw_artifact_ref"),
        metadata=_dict_or_empty(memory_payload.get("metadata")),
    )


def _claim_from_payload(value: Any) -> ClaimMemory:
    payload = _payload(value)
    nested = _dict_or_empty(payload.get("payload"))
    memory_payload = nested if "claim_id" in nested else payload
    return ClaimMemory(
        claim_id=str(memory_payload.get("claim_id") or payload.get("claim_id") or ""),
        run_id=str(memory_payload.get("run_id") or payload.get("run_id") or ""),
        text=str(memory_payload.get("text") or payload.get("text") or ""),
        status=str(memory_payload.get("status") or payload.get("status") or "uncertain"),  # type: ignore[arg-type]
        confidence=float(memory_payload.get("confidence") or payload.get("confidence") or 0.5),
        subject_entity_id=memory_payload.get("subject_entity_id"),
        predicate=memory_payload.get("predicate"),
        object_entity_id=memory_payload.get("object_entity_id"),
        value=_dict_or_empty(memory_payload.get("value")),
        valid_at=_dt(memory_payload.get("valid_at")),
        invalid_at=_dt(memory_payload.get("invalid_at")),
        first_seen_at=_dt(memory_payload.get("first_seen_at") or payload.get("created_at")) or datetime.now(UTC),
        last_seen_at=_dt(memory_payload.get("last_seen_at")) or datetime.now(UTC),
        evidence_ids=_str_list(
            memory_payload.get("evidence_ids")
            or payload.get("supporting_evidence_ids")
            or payload.get("supporting_evidence_ids")
        ),
        contradicted_by=_str_list(memory_payload.get("contradicted_by") or payload.get("rejecting_evidence_ids")),
        metadata=_dict_or_empty(memory_payload.get("metadata")),
    )


def _entity_from_row(row: tuple[Any, ...]) -> EntityMemory:
    return EntityMemory(
        entity_id=str(row[0]),
        entity_type=str(row[1]),  # type: ignore[arg-type]
        canonical_name=str(row[2]),
        aliases=_str_list(row[3]),
        summary=row[4],
        first_seen_at=_dt(row[5]) or datetime.now(UTC),
        last_seen_at=_dt(row[6]) or datetime.now(UTC),
        importance_score=float(row[7] or 0.0),
        trend_score=float(row[8] or 0.0),
        external_refs=_dict_or_empty(row[9]),
        metadata=_dict_or_empty(row[10]),
    )


def _event_from_row(row: tuple[Any, ...]) -> EventMemory:
    return EventMemory(
        event_id=str(row[0]),
        event_type=str(row[1]),  # type: ignore[arg-type]
        title=str(row[2]),
        summary=str(row[3] or ""),
        run_id=str(row[4]),
        event_time=_dt(row[5]),
        detected_at=_dt(row[6]) or datetime.now(UTC),
        topic=row[7],
        impact_score=float(row[8] or 0.0),
        novelty_score=float(row[9] or 0.0),
        status=str(row[10] or "active"),
        metadata=_dict_or_empty(row[11]),
        entity_ids=_str_list(row[12]),
        claim_ids=_str_list(row[13]),
        evidence_ids=_str_list(row[14]),
    )


def _decision_from_row(row: tuple[Any, ...]) -> DecisionMemory:
    return DecisionMemory(
        decision_id=str(row[0]),
        decision_type=str(row[1]),
        target_type=str(row[2]),
        target_id=str(row[3]),
        decision=str(row[4]),
        reason=row[5],
        run_id=str(row[6]),
        graph_id=row[7],
        graph_version=row[8],
        graph_ref=row[9],
        graph_checksum=row[10],
        agent_id=row[11],
        input_features=_dict_or_empty(row[12]),
        output_scores=_dict_or_empty(row[13]),
        created_at=_dt(row[14]) or datetime.now(UTC),
        metadata=_dict_or_empty(row[15]),
    )


def _preference_from_row(row: tuple[Any, ...]) -> PreferenceMemory:
    return PreferenceMemory(
        preference_id=str(row[0]),
        owner_type=str(row[1]),
        owner_id=str(row[2]),
        preference_type=str(row[3]),
        content=str(row[4]),
        weight=float(row[5] or 1.0),
        source=str(row[6] or "system"),
        created_at=_dt(row[7]) or datetime.now(UTC),
        updated_at=_dt(row[8]),
        expires_at=_dt(row[9]),
        metadata=_dict_or_empty(row[10]),
    )


def _dict_or_empty(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    try:
        return dict(value)
    except (TypeError, ValueError):
        return {}


def _str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            value = parsed
        else:
            return [value] if value else []
    if isinstance(value, tuple | set):
        value = list(value)
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None and str(item).strip()]


def _dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


__all__ = ["PostgresIntelligenceMemoryRepository"]
