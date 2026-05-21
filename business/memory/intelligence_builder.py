from __future__ import annotations

import hashlib
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from typing import Any, cast

from business.memory.intelligence_models import (
    ClaimMemory,
    DecisionMemory,
    EntityMemory,
    EventMemory,
    EvidenceMemory,
    IntelligenceMemoryBundle,
)


class IntelligenceMemoryBuilder:
    def build_from_run_output(
        self,
        output: dict[str, Any],
        *,
        run_id: str,
        report_id: str | None = None,
        topic: str | None = None,
    ) -> IntelligenceMemoryBundle:
        resolved_topic = topic or _topic_from_output(output)
        evidence = self.build_evidence(output, run_id=run_id, topic=resolved_topic)
        claims = self.build_claims(output, run_id=run_id, evidence=evidence, topic=resolved_topic)
        entities = self.build_entities(output, evidence=evidence, claims=claims, topic=resolved_topic)
        events = self.build_events(
            output,
            run_id=run_id,
            evidence=evidence,
            claims=claims,
            entities=entities,
            topic=resolved_topic,
        )
        decisions = self.build_decisions(output, run_id=run_id, report_id=report_id)
        return IntelligenceMemoryBundle(
            run_id=run_id,
            topic=resolved_topic,
            evidence=evidence,
            claims=claims,
            entities=entities,
            events=events,
            decisions=decisions,
            preferences=[],
        )

    def build_evidence(
        self,
        output: dict[str, Any],
        *,
        run_id: str,
        topic: str | None = None,
    ) -> list[EvidenceMemory]:
        items = _first_non_empty_list(
            _get_path(output, "evidence_bundle", "items"),
            output.get("evidence_items"),
            _get_path(output, "final_report", "evidence"),
            _get_path(output, "blocked_report", "evidence"),
        )
        evidence: list[EvidenceMemory] = []
        for item in items:
            payload = _to_dict(item)
            metadata = safe_dict(payload.get("metadata"))
            title = _first_text(payload.get("title"), payload.get("claim"), default="Untitled evidence")
            summary = _first_text(payload.get("summary"), payload.get("claim"), default="")
            source_urls = safe_str_list(payload.get("source_urls"))
            if not source_urls and payload.get("source_url") is not None:
                source_urls = safe_str_list([payload.get("source_url")])
            source_item_ids = safe_str_list(payload.get("source_item_ids"))
            if not source_item_ids and payload.get("source_item_id") is not None:
                source_item_ids = safe_str_list([payload.get("source_item_id")])
            evidence_id = _optional_text(payload.get("evidence_id")) or stable_id(
                "evidence",
                run_id,
                title,
                summary,
                prefix="evidence",
            )
            evidence.append(
                EvidenceMemory(
                    evidence_id=evidence_id,
                    run_id=run_id,
                    title=title,
                    summary=summary,
                    source_urls=source_urls,
                    source_item_ids=source_item_ids,
                    confidence=safe_float(payload.get("confidence"), 0.5),
                    category=_first_text(payload.get("category"), metadata.get("category"), default="news"),
                    published_at=_parse_dt(payload.get("published_at") or metadata.get("published_at")),
                    fetched_at=_parse_dt(payload.get("fetched_at") or metadata.get("fetched_at")),
                    topic=topic,
                    source_name=_optional_text(payload.get("source_name") or metadata.get("source_name")),
                    source_id=_optional_text(payload.get("source_id") or metadata.get("source_id")),
                    content_hash=_optional_text(payload.get("content_hash") or metadata.get("content_hash")),
                    raw_artifact_ref=_artifact_ref(payload.get("raw_artifact_ref") or metadata.get("raw_artifact_ref")),
                    metadata=metadata,
                )
            )
        return evidence

    def build_claims(
        self,
        output: dict[str, Any],
        *,
        run_id: str,
        evidence: list[EvidenceMemory],
        topic: str | None = None,
    ) -> list[ClaimMemory]:
        del output, topic
        claims_by_key: dict[str, ClaimMemory] = {}
        for item in evidence:
            text = (item.summary or item.title).strip()
            if not text:
                continue
            key = normalize_text_key(text)
            claim = claims_by_key.get(key)
            if claim is None:
                claims_by_key[key] = ClaimMemory(
                    claim_id=stable_id("claim", key, prefix="claim"),
                    run_id=run_id,
                    text=text,
                    status="active",
                    confidence=item.confidence,
                    evidence_ids=[item.evidence_id],
                    metadata={"source": "evidence_memory_builder"},
                )
            else:
                claims_by_key[key] = claim.with_evidence(item.evidence_id)
        return list(claims_by_key.values())

    def build_entities(
        self,
        output: dict[str, Any],
        *,
        evidence: list[EvidenceMemory],
        claims: list[ClaimMemory],
        topic: str | None = None,
    ) -> list[EntityMemory]:
        del output, claims
        entities: dict[str, EntityMemory] = {}
        if topic:
            entity = _entity("topic", topic, metadata={"source": "topic"})
            entities[entity.entity_id] = entity
        for item in evidence:
            if item.source_name:
                entity = _entity(
                    "source",
                    item.source_name,
                    external_refs={"source_id": item.source_id} if item.source_id else {},
                    metadata={"source": "evidence.source_name"},
                )
                entities[entity.entity_id] = entity
            metadata = dict(item.metadata)
            github_repo = _optional_text(metadata.get("github_repo") or metadata.get("repo"))
            if github_repo:
                entity = _entity(
                    "repository",
                    github_repo,
                    external_refs={"github_repo": github_repo},
                    metadata={"source": "evidence.metadata.github_repo"},
                )
                entities[entity.entity_id] = entity
            paper_id = _optional_text(metadata.get("paper_id") or metadata.get("arxiv_id"))
            if paper_id:
                entity = _entity(
                    "paper",
                    paper_id,
                    external_refs={"paper_id": paper_id},
                    metadata={"source": "evidence.metadata.paper_id"},
                )
                entities[entity.entity_id] = entity
        return list(entities.values())

    def build_events(
        self,
        output: dict[str, Any],
        *,
        run_id: str,
        evidence: list[EvidenceMemory],
        claims: list[ClaimMemory],
        entities: list[EntityMemory],
        topic: str | None = None,
    ) -> list[EventMemory]:
        del output
        if not evidence and not claims:
            return []
        label = topic or "run"
        summary = " ".join(claim.text for claim in claims[:3]).strip()
        if not summary:
            summary = " ".join(item.summary or item.title for item in evidence[:3]).strip()
        return [
            EventMemory(
                event_id=stable_id("event", run_id, label, summary, prefix="event"),
                event_type="general_news",
                title=f"NewsRoom detected update for {label}",
                summary=summary,
                run_id=run_id,
                topic=topic,
                entity_ids=[item.entity_id for item in entities],
                claim_ids=[item.claim_id for item in claims],
                evidence_ids=[item.evidence_id for item in evidence],
                impact_score=min(1.0, len(evidence) / 10.0),
                novelty_score=0.5,
                metadata={"source": "coarse_phase1_event"},
            )
        ]

    def build_decisions(
        self,
        output: dict[str, Any],
        *,
        run_id: str,
        report_id: str | None = None,
    ) -> list[DecisionMemory]:
        decisions: list[DecisionMemory] = []
        for key in ("quality_result", "verification_result", "review_result"):
            payload = _to_dict(output.get(key))
            if payload:
                decisions.append(_decision_from_payload(payload, run_id=run_id, report_id=report_id, source_key=key))
        final_quality = _to_dict(_get_path(output, "final_report", "quality"))
        if final_quality:
            decisions.append(
                _decision_from_payload(
                    final_quality,
                    run_id=run_id,
                    report_id=report_id,
                    source_key="final_report.quality",
                )
            )
        return _dedupe_decisions(decisions)


def stable_id(*parts: Any, prefix: str | None = None, length: int = 24) -> str:
    raw = ":".join(str(part) for part in parts if part is not None)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:length]
    return f"{prefix}:{digest}" if prefix else digest


def normalize_text_key(text: str) -> str:
    return " ".join(str(text).casefold().split())


def safe_float(value: Any, default: float = 0.5) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def safe_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        values = [value]
    elif isinstance(value, list | tuple | set):
        values = list(value)
    else:
        return []
    result: list[str] = []
    for item in values:
        if item is None:
            continue
        text = str(item).strip()
        if text:
            result.append(text)
    return result


def _decision_from_payload(
    payload: dict[str, Any],
    *,
    run_id: str,
    report_id: str | None,
    source_key: str,
) -> DecisionMemory:
    target_id = report_id or f"{run_id}:final"
    decision = _first_text(payload.get("decision"), payload.get("status"), payload.get("route"), default="unknown")
    reason = _optional_text(payload.get("reason"))
    reasons = payload.get("reasons")
    if reason is None and isinstance(reasons, list) and reasons:
        reason = "; ".join(str(item) for item in reasons if item is not None)
    input_features = safe_dict(payload.get("scores") or payload.get("input_features"))
    output_scores = safe_dict(payload.get("metrics") or payload.get("output_scores"))
    for key in (
        "quality_score",
        "citation_coverage_score",
        "claim_support_score",
        "evidence_alignment_score",
        "support_coverage",
    ):
        if key in payload and payload[key] is not None:
            output_scores.setdefault(key, payload[key])
    return DecisionMemory(
        decision_id=stable_id("decision", run_id, source_key, target_id, decision, prefix="decision"),
        decision_type="quality_gate" if "quality" in source_key else source_key,
        target_type="report",
        target_id=target_id,
        decision=decision,
        run_id=run_id,
        reason=reason,
        agent_id=_optional_text(payload.get("agent_id")),
        workflow_id=_optional_text(payload.get("workflow_id")),
        input_features=input_features,
        output_scores=output_scores,
        metadata={"source_key": source_key, "payload": payload},
    )


def _dedupe_decisions(decisions: list[DecisionMemory]) -> list[DecisionMemory]:
    seen: set[str] = set()
    result: list[DecisionMemory] = []
    for decision in decisions:
        if decision.decision_id in seen:
            continue
        seen.add(decision.decision_id)
        result.append(decision)
    return result


def _entity(
    entity_type: str,
    name: str,
    *,
    external_refs: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> EntityMemory:
    return EntityMemory(
        entity_id=stable_id("entity", entity_type, normalize_text_key(name), prefix="entity"),
        entity_type=cast(Any, entity_type),
        canonical_name=name.strip(),
        external_refs=external_refs or {},
        metadata=metadata or {},
    )


def _first_non_empty_list(*values: Any) -> list[Any]:
    for value in values:
        if value is None:
            continue
        if isinstance(value, list) and value:
            return list(value)
        if isinstance(value, tuple) and value:
            return list(value)
    return []


def _topic_from_output(output: dict[str, Any]) -> str | None:
    for path in (
        ("request", "topic"),
        ("evidence_bundle", "topic"),
        ("final_report", "topic"),
        ("final_report", "metadata", "topic"),
        ("blocked_report", "topic"),
        ("blocked_report", "metadata", "topic"),
    ):
        value = _get_path(output, *path)
        text = _optional_text(value)
        if text:
            return text
    return None


def _get_path(value: Any, *path: str) -> Any:
    current = value
    for key in path:
        payload = _to_dict(current)
        if not payload or key not in payload:
            return None
        current = payload[key]
    return current


def _first_text(*values: Any, default: str) -> str:
    for value in values:
        text = _optional_text(value)
        if text:
            return text
    return default


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
        return dict(payload) if isinstance(payload, dict) else {}
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        payload = model_dump(mode="json")
        return dict(payload) if isinstance(payload, dict) else {}
    if is_dataclass(value):
        return asdict(value)
    try:
        return dict(value)
    except (TypeError, ValueError):
        return {}


def _parse_dt(value: Any) -> datetime | None:
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


def _artifact_ref(value: Any) -> str | None:
    payload = _to_dict(value)
    if payload:
        return _optional_text(payload.get("artifact_id") or payload.get("path") or payload.get("uri"))
    return _optional_text(value)


__all__ = [
    "IntelligenceMemoryBuilder",
    "normalize_text_key",
    "safe_dict",
    "safe_float",
    "safe_str_list",
    "stable_id",
]
