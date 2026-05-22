from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from framework.specs import EdgeSpec, StepSpec, WorkflowSpec

from business.boards._feedback import BoardFeedbackService
from business.boards._improvement import BoardImprovementService
from business.boards._service import BoardServiceBase
from business.foundation import AnalysisContext, BoardType, RunContext, Signal
from business.foundation.skills import BusinessSkillRuntime
from business.foundation.subscription import DeliveryPlanBuilder, SubscriptionPayloadBuilder
from business.layers.signal import SignalPipeline


PRODUCTIZED_BOARD_STEPS = (
    "prepare_signals",
    "classify_board_signals",
    "extract_entities",
    "build_evidence",
    "deduplicate_events",
    "rank_items",
    "analyze_trends",
    "build_board_output",
    "build_quality_summary",
    "build_subscription_payload",
    "build_feedback_events",
    "build_improvement_recommendations",
    "publish_board_artifacts",
)


class ProductizedBoardSteps:
    def __init__(
        self,
        *,
        board_type: BoardType,
        board_service: BoardServiceBase,
        skill_runtime: BusinessSkillRuntime,
        feedback_service: BoardFeedbackService,
        improvement_service: BoardImprovementService,
    ) -> None:
        self.board_type = board_type
        self.board_service = board_service
        self.skill_runtime = skill_runtime
        self.feedback_service = feedback_service
        self.improvement_service = improvement_service

    def register(self, registry: Any) -> None:
        prefix = self.board_type.value
        registry.register(f"{prefix}.prepare_signals", self.prepare_signals)
        registry.register(f"{prefix}.classify_board_signals", self.classify_board_signals)
        registry.register(f"{prefix}.extract_entities", self.extract_entities)
        registry.register(f"{prefix}.build_evidence", self.build_evidence)
        registry.register(f"{prefix}.deduplicate_events", self.deduplicate_events)
        registry.register(f"{prefix}.rank_items", self.rank_items)
        registry.register(f"{prefix}.analyze_trends", self.analyze_trends)
        registry.register(f"{prefix}.build_board_output", self.build_board_output)
        registry.register(f"{prefix}.build_quality_summary", self.build_quality_summary)
        registry.register(f"{prefix}.build_subscription_payload", self.build_subscription_payload)
        registry.register(f"{prefix}.build_feedback_events", self.build_feedback_events)
        registry.register(f"{prefix}.build_improvement_recommendations", self.build_improvement_recommendations)
        registry.register(f"{prefix}.publish_board_artifacts", self.publish_board_artifacts)

    def prepare_signals(self, buffer: Any) -> dict[str, Any]:
        request = buffer.read("request")
        run_id = _run_id(request, self.board_type)
        context = _context(self.board_type, request, run_id)
        raw_signals = list(request.get("signals") or [])
        pipeline_result = SignalPipeline().coerce_signals(
            raw_signals,
            context=context,
            board_type=self.board_type,
            topic=request.get("topic"),
        )
        skill_traces: list[dict[str, Any]] = []
        reliability_results = []
        for signal in pipeline_result.signals:
            source_result = self.skill_runtime.run_source_reliability(
                _source_payload(signal),
                _content_payload(signal),
                run_id=run_id,
                fail_on_skill_error=bool(request.get("fail_on_skill_error", False)),
            )
            reliability_results.append(source_result.output)
            skill_traces.append(source_result.to_dict())
        improvement_context = self.improvement_service.apply_approved_overrides(
            run_id=run_id,
            board_type=self.board_type.value,
        )
        return {
            "context": context,
            "raw_signals": raw_signals,
            "prepared_signals": pipeline_result.signals,
            "source_reliability_results": reliability_results,
            "skill_traces": skill_traces,
            "improvement_context": improvement_context.to_dict(),
        }

    def classify_board_signals(self, buffer: Any) -> dict[str, Any]:
        context = buffer.read("context")
        prepared_signals = buffer.read("prepared_signals")
        selected = self.board_service._select_signals(prepared_signals, context=context)
        return {"board_signals": selected}

    def extract_entities(self, buffer: Any) -> dict[str, Any]:
        request = buffer.read("request")
        run_id = _run_id(request, self.board_type)
        skill_traces = list(buffer.read("skill_traces"))
        extracted = []
        for signal in buffer.read("board_signals"):
            result = self.skill_runtime.run_entity_extraction(
                _signal_item_payload(signal),
                run_id=run_id,
                fail_on_skill_error=bool(request.get("fail_on_skill_error", False)),
            )
            extracted.append({"signal_id": signal.signal_id, **result.output})
            skill_traces.append(result.to_dict())
        return {"extracted_entities": extracted, "skill_traces": skill_traces}

    def build_evidence(self, buffer: Any) -> dict[str, Any]:
        evidence_items = []
        evidence_refs = []
        extracted_entities = buffer.read("extracted_entities")
        entities_by_signal = {
            item.get("signal_id"): item.get("entities", [])
            for item in extracted_entities
            if isinstance(item, dict)
        }
        for signal in buffer.read("board_signals"):
            ref = signal.source.to_dict()
            evidence_refs.append(ref)
            evidence_items.append(
                {
                    "source_id": signal.source.source_id,
                    "source_item_id": signal.source.external_id or signal.signal_id,
                    "title": signal.title,
                    "summary": signal.summary or signal.content or signal.title,
                    "url": signal.url,
                    "entities": entities_by_signal.get(signal.signal_id, []),
                }
            )
        return {"evidence_refs": evidence_refs, "evidence_items": evidence_items}

    def deduplicate_events(self, buffer: Any) -> dict[str, Any]:
        request = buffer.read("request")
        run_id = _run_id(request, self.board_type)
        skill_traces = list(buffer.read("skill_traces"))
        items = [_signal_item_payload(signal) for signal in buffer.read("board_signals")]
        result = self.skill_runtime.run_event_deduplication(
            items,
            run_id=run_id,
            fail_on_skill_error=bool(request.get("fail_on_skill_error", False)),
        )
        skill_traces.append(result.to_dict())
        return {
            "deduplicated_signals": buffer.read("board_signals"),
            "deduplication_result": result.output,
            "skill_traces": skill_traces,
        }

    def rank_items(self, buffer: Any) -> dict[str, Any]:
        signals = sorted(buffer.read("deduplicated_signals"), key=_signal_rank_key, reverse=True)
        return {"ranked_signals": signals}

    def analyze_trends(self, buffer: Any) -> dict[str, Any]:
        request = buffer.read("request")
        run_id = _run_id(request, self.board_type)
        skill_traces = list(buffer.read("skill_traces"))
        events = _trend_events(buffer.read("deduplication_result"), buffer.read("ranked_signals"))
        result = self.skill_runtime.run_trend_analysis(
            events,
            run_id=run_id,
            fail_on_skill_error=bool(request.get("fail_on_skill_error", False)),
        )
        skill_traces.append(result.to_dict())
        return {"trend_analysis": result.output, "skill_traces": skill_traces}

    def build_board_output(self, buffer: Any) -> dict[str, Any]:
        request = buffer.read("request")
        context = buffer.read("context")
        result = self.board_service.build_board_run_result(buffer.read("ranked_signals"), context=context)
        skill_traces = list(buffer.read("skill_traces"))
        report_result = self.skill_runtime.run_report_writing(
            {
                "title": f"{self.board_service.board_definition.name} Summary",
                "audience": "subscriber",
                "style": "concise",
            },
            [_card_report_item(card) for card in result.cards],
            trend_analyses=list(buffer.read("trend_analysis").get("event_analyses", [])),
            run_id=_run_id(request, self.board_type),
            fail_on_skill_error=bool(request.get("fail_on_skill_error", False)),
        )
        skill_traces.append(report_result.to_dict())
        metadata = {
            **dict(result.metadata),
            "skill_trace_metadata": skill_traces,
            "extracted_entities": buffer.read("extracted_entities"),
            "evidence_items": buffer.read("evidence_items"),
            "trend_analysis": buffer.read("trend_analysis"),
            "deduplication_result": buffer.read("deduplication_result"),
            "improvement_context": buffer.read("improvement_context"),
        }
        result = result.model_copy(update={"metadata": metadata})
        board_output = dict(result.metadata.get("board_output") or {})
        board_output.setdefault("metadata", {})
        if isinstance(board_output["metadata"], dict):
            board_output["metadata"].update(
                {
                    "skill_trace_metadata": skill_traces,
                    "improvement_context": buffer.read("improvement_context"),
                    "trend_analysis": buffer.read("trend_analysis"),
                }
            )
        return {
            "board_run_result": result,
            "board_output": board_output,
            "cards": [card.to_dict() for card in result.cards],
            "detail_pages": [page.to_dict() for page in result.detail_pages],
            "insights": [insight.to_dict() for insight in result.insights],
            "summary_md": report_result.output.get("markdown_report", _summary_markdown(result)),
            "skill_traces": skill_traces,
        }

    def build_quality_summary(self, buffer: Any) -> dict[str, Any]:
        request = buffer.read("request")
        run_id = _run_id(request, self.board_type)
        skill_traces = list(buffer.read("skill_traces"))
        result = buffer.read("board_run_result")
        evidence_items = buffer.read("evidence_items")
        claims = [
            {"claim_id": f"claim-{index}", "text": card.summary, "citation_source_ids": [ref.get("source_id") for ref in buffer.read("evidence_refs") if isinstance(ref, dict)]}
            for index, card in enumerate(result.cards)
        ] or [{"claim_id": "empty", "text": "No cards"}]
        sources = [
            {"source_id": str(item.get("source_id") or index), "text": str(item.get("summary") or item.get("title") or ""), "url": str(item.get("url") or "")}
            for index, item in enumerate(evidence_items)
        ] or [{"source_id": "empty", "text": "No sources"}]
        evidence_check = self.skill_runtime.run_evidence_checking(
            claims,
            sources,
            run_id=run_id,
            fail_on_skill_error=bool(request.get("fail_on_skill_error", False)),
        )
        skill_traces.append(evidence_check.to_dict())
        quality = result.quality_summary.to_dict() if result.quality_summary is not None else {"status": "unchecked", "score": None}
        quality["evidence_checking"] = evidence_check.output
        quality["skill_trace_metadata"] = skill_traces
        return {"quality_summary": quality, "evidence_checking": evidence_check.output, "skill_traces": skill_traces}

    def build_subscription_payload(self, buffer: Any) -> dict[str, Any]:
        request = buffer.read("request")
        result = buffer.read("board_run_result")
        quality = buffer.read("quality_summary")
        quality_score = quality.get("score") if isinstance(quality, dict) else None
        payload = SubscriptionPayloadBuilder().build(
            run_id=_run_id(request, self.board_type),
            board_type=self.board_type.value,
            topic=request.get("topic"),
            cards=result.cards,
            summary=str(buffer.read("board_output").get("metadata", {}).get("report", {}).get("summary") or f"{self.board_type.value} summary"),
            quality_score=float(quality_score) if quality_score is not None else None,
        )
        delivery_plan = DeliveryPlanBuilder().build(payload)
        return {"subscription_payload": {**payload.to_dict(), "delivery_plan": delivery_plan.to_dict()}}

    def build_feedback_events(self, buffer: Any) -> dict[str, Any]:
        result = buffer.read("board_run_result")
        events = self.feedback_service.collect(
            board_run_result=result,
            quality_summary=result.quality_summary,
        )
        events = self.improvement_service.collect_feedback(events)
        signals = self.improvement_service.build_learning_signals(events)
        return {
            "feedback_events": [event.to_dict() for event in events],
            "learning_signals": [signal.to_dict() for signal in signals],
        }

    def build_improvement_recommendations(self, buffer: Any) -> dict[str, Any]:
        request = buffer.read("request")
        run_id = _run_id(request, self.board_type)
        quality = buffer.read("quality_summary")
        feedback_events = [
            _feedback_event_from_dict(item)
            for item in buffer.read("feedback_events")
            if isinstance(item, dict)
        ]
        learning_signals = [
            _learning_signal_from_dict(item)
            for item in buffer.read("learning_signals")
            if isinstance(item, dict)
        ]
        recommendations = self.improvement_service.build_recommendations(
            learning_signals,
            board_type=self.board_type.value,
            quality_summary=quality,
        )
        proposals = self.improvement_service.build_proposals(recommendations)
        improvement_context = self.improvement_service.apply_approved_overrides(
            run_id=run_id,
            board_type=self.board_type.value,
        )
        measurement = self.improvement_service.measure(
            request.get("previous_measurement_baseline"),
            _measurement_snapshot(buffer),
        )
        report = self.improvement_service.build_report(
            feedback_events=feedback_events,
            learning_signals=learning_signals,
            recommendations=recommendations,
            proposals=proposals,
            applied_overrides=improvement_context.applied_overrides,
            measurement=measurement,
        )
        return {
            "improvement_recommendations": [item.to_dict() for item in recommendations],
            "improvement_proposals": [item.to_dict() for item in proposals],
            "applied_overrides": improvement_context.applied_overrides,
            "improvement_measurement": measurement.to_dict(),
            "self_improvement_report": report.to_dict(),
        }

    def publish_board_artifacts(self, buffer: Any) -> dict[str, Any]:
        request = buffer.read("request")
        quality = buffer.read("quality_summary")
        return {
            "artifact_metadata": {
                "board_type": self.board_type.value,
                "run_id": _run_id(request, self.board_type),
                "topic": request.get("topic"),
                "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "schema_version": "business.board.productized.v1",
                "source_count": len(request.get("signals") or []),
                "card_count": len(buffer.read("cards")),
                "quality_score": quality.get("score") if isinstance(quality, dict) else None,
                "subscription_ready": bool(buffer.read("subscription_payload").get("delivery_hints", {}).get("subscription_ready")),
                "improvement_ready": True,
            }
        }


def build_productized_board_workflow(board_type: BoardType) -> WorkflowSpec:
    workflow_id = f"{board_type.value}-productized-board"
    steps = []
    for step_id in PRODUCTIZED_BOARD_STEPS:
        steps.append(
            StepSpec(
                step_id=step_id,
                name=step_id.replace("_", " ").title(),
                implementation=f"{board_type.value}.{step_id}",
                read_keys=_read_keys(step_id),
                write_keys=_write_keys(step_id),
                required_output_keys=_write_keys(step_id),
            )
        )
    return WorkflowSpec(
        workflow_id=workflow_id,
        name=f"{board_type.value} Productized Board",
        version="1.0.0",
        description=f"Productized business workflow for {board_type.value}.",
        start_step_id=PRODUCTIZED_BOARD_STEPS[0],
        terminal_step_ids=[PRODUCTIZED_BOARD_STEPS[-1]],
        steps=steps,
        edges=[
            EdgeSpec(
                edge_id=f"{left}_to_{right}",
                source_step_id=left,
                target_step_id=right,
            )
            for left, right in zip(PRODUCTIZED_BOARD_STEPS, PRODUCTIZED_BOARD_STEPS[1:])
        ],
        input_schema={
            "type": "object",
            "required": ["signals"],
            "properties": {
                "signals": {"type": "array"},
                "topic": {"type": ["string", "null"]},
                "run_id": {"type": ["string", "null"]},
            },
        },
        output_schema={"type": "object"},
        metadata={"board_type": board_type.value, "productized": True},
    )


def _read_keys(step_id: str) -> list[str]:
    mapping = {
        "prepare_signals": ["request"],
        "classify_board_signals": ["context", "prepared_signals"],
        "extract_entities": ["request", "board_signals", "skill_traces"],
        "build_evidence": ["board_signals", "extracted_entities"],
        "deduplicate_events": ["request", "board_signals", "extracted_entities", "skill_traces"],
        "rank_items": ["deduplicated_signals", "improvement_context"],
        "analyze_trends": ["request", "ranked_signals", "deduplication_result", "skill_traces"],
        "build_board_output": ["request", "context", "ranked_signals", "extracted_entities", "evidence_refs", "evidence_items", "trend_analysis", "deduplication_result", "improvement_context", "skill_traces"],
        "build_quality_summary": ["request", "board_run_result", "evidence_items", "evidence_refs", "skill_traces"],
        "build_subscription_payload": ["request", "board_run_result", "board_output", "cards", "quality_summary"],
        "build_feedback_events": ["board_run_result", "quality_summary"],
        "build_improvement_recommendations": ["request", "board_run_result", "quality_summary", "cards", "feedback_events", "learning_signals", "subscription_payload"],
        "publish_board_artifacts": ["request", "cards", "quality_summary", "subscription_payload"],
    }
    return mapping[step_id]


def _write_keys(step_id: str) -> list[str]:
    mapping = {
        "prepare_signals": ["context", "raw_signals", "prepared_signals", "source_reliability_results", "skill_traces", "improvement_context"],
        "classify_board_signals": ["board_signals"],
        "extract_entities": ["extracted_entities", "skill_traces"],
        "build_evidence": ["evidence_refs", "evidence_items"],
        "deduplicate_events": ["deduplicated_signals", "deduplication_result", "skill_traces"],
        "rank_items": ["ranked_signals"],
        "analyze_trends": ["trend_analysis", "skill_traces"],
        "build_board_output": ["board_run_result", "board_output", "cards", "detail_pages", "insights", "summary_md", "skill_traces"],
        "build_quality_summary": ["quality_summary", "evidence_checking", "skill_traces"],
        "build_subscription_payload": ["subscription_payload"],
        "build_feedback_events": ["feedback_events", "learning_signals"],
        "build_improvement_recommendations": ["improvement_recommendations", "improvement_proposals", "applied_overrides", "improvement_measurement", "self_improvement_report"],
        "publish_board_artifacts": ["artifact_metadata"],
    }
    return mapping[step_id]


def _context(board_type: BoardType, request: dict[str, Any], run_id: str) -> AnalysisContext:
    return AnalysisContext(
        run_context=RunContext(run_id=run_id, run_type="board_productized", profile="productized"),
        board_type=board_type,
        metadata={"topic": request.get("topic"), "productized": True},
        enable_llm=False,
    )


def _run_id(request: dict[str, Any], board_type: BoardType) -> str:
    return str(request.get("run_id") or f"{board_type.value}-productized-run")


def _source_payload(signal: Signal) -> dict[str, Any]:
    return {
        "name": signal.source.source_name,
        "url": signal.url or signal.source.source_url or "https://example.com",
        "publisher_type": _publisher_type(signal.source.source_type.value),
        "known_reputation": str(signal.source.reliability.value),
    }


def _content_payload(signal: Signal) -> dict[str, Any]:
    return {
        "title": signal.title,
        "url": signal.url or "",
        "published_at": signal.published_at.isoformat().replace("+00:00", "Z") if signal.published_at else "",
        "author": ", ".join(signal.authors),
        "raw_text": signal.content or signal.summary or signal.title,
    }


def _signal_item_payload(signal: Signal) -> dict[str, Any]:
    return {
        "id": signal.signal_id,
        "item_id": signal.signal_id,
        "signal_id": signal.signal_id,
        "source_item_id": signal.source.external_id or signal.signal_id,
        "title": signal.title,
        "summary": signal.summary or "",
        "content": signal.content or "",
        "url": signal.url or "",
        "source_name": signal.source.source_name,
        "published_at": signal.published_at.isoformat().replace("+00:00", "Z") if signal.published_at else "",
        "entities": [],
    }


def _publisher_type(source_type: str) -> str:
    if source_type in {"official_blog", "rss", "web_page", "html"}:
        return "official_blog" if source_type == "official_blog" else "news_media"
    if source_type in {"arxiv", "paper_index"}:
        return "research_platform"
    if source_type == "github":
        return "github"
    if source_type in {"hackernews", "reddit", "github_discussion", "lobsters", "stackoverflow", "devto"}:
        return "community"
    return "unknown"


def _signal_rank_key(signal: Signal) -> tuple[float, float, str]:
    final_score = float(signal.metrics.get("final_score", 0.5)) if isinstance(signal.metrics, dict) else 0.5
    confidence = signal.confidence.value if signal.confidence is not None else 0.5
    return final_score, confidence, signal.signal_id


def _trend_events(deduplication_result: dict[str, Any], signals: list[Signal]) -> list[dict[str, Any]]:
    groups = deduplication_result.get("event_groups") if isinstance(deduplication_result, dict) else None
    if groups:
        return [
            {
                "event_id": str(group.get("event_id")),
                "title": _title_for_group(group, signals),
                "summary": "Grouped board event.",
                "item_ids": list(group.get("item_ids") or []),
                "source_count": len(group.get("item_ids") or []),
                "primary_source_count": 1,
                "community_signal_count": sum(1 for signal in signals if signal.signal_type.value == "community_discussion"),
                "evidence_status": "supported",
                "impact_hints": ["engineering"],
            }
            for group in groups
            if isinstance(group, dict)
        ]
    return [
        {
            "event_id": signal.signal_id,
            "title": signal.title,
            "summary": signal.summary or signal.content or signal.title,
            "item_ids": [signal.signal_id],
            "source_count": 1,
            "primary_source_count": 1,
            "community_signal_count": 1 if signal.signal_type.value == "community_discussion" else 0,
            "evidence_status": "supported",
            "impact_hints": ["engineering"],
        }
        for signal in signals
    ]


def _title_for_group(group: dict[str, Any], signals: list[Signal]) -> str:
    ids = {str(item) for item in group.get("item_ids") or []}
    for signal in signals:
        if signal.signal_id in ids or (signal.source.external_id and signal.source.external_id in ids):
            return signal.title
    return str(group.get("event_id") or "Event")


def _card_report_item(card: Any) -> dict[str, Any]:
    payload = card.to_dict() if hasattr(card, "to_dict") else dict(card)
    evidence_refs = payload.get("evidence_refs") or []
    first_source = evidence_refs[0] if evidence_refs and isinstance(evidence_refs[0], dict) else {}
    return {
        "item_id": payload.get("card_id"),
        "title": payload.get("title"),
        "summary": payload.get("summary"),
        "url": first_source.get("url") or first_source.get("source_url") or "",
        "source_name": first_source.get("source_name") or "source",
        "evidence_status": "supported" if evidence_refs else "unclear",
        "trend_score": payload.get("score", {}).get("value", 0.5) if isinstance(payload.get("score"), dict) else 0.5,
        "why_it_matters": payload.get("ranking_reason") or payload.get("summary"),
    }


def _summary_markdown(result: Any) -> str:
    title = f"{result.board_type.value} summary"
    lines = [f"# {title}", ""]
    for card in result.cards:
        lines.append(f"- {card.title}: {card.summary}")
    return "\n".join(lines) + "\n"


def _measurement_snapshot(buffer: Any) -> dict[str, Any]:
    quality = buffer.read("quality_summary")
    cards = buffer.read("cards")
    subscription = buffer.read("subscription_payload")
    return {
        "quality_score": quality.get("score") if isinstance(quality, dict) else None,
        "card_count": len(cards),
        "evidence_coverage": _evidence_coverage(cards),
        "duplicate_rate": _duplicate_rate(buffer.read("board_run_result")),
        "empty_output": len(cards) == 0,
        "subscription_match": 1.0 if subscription.get("targets") else 0.0,
    }


def _evidence_coverage(cards: list[dict[str, Any]]) -> float:
    if not cards:
        return 0.0
    return round(sum(1 for card in cards if card.get("evidence_refs")) / len(cards), 4)


def _duplicate_rate(result: Any) -> float:
    metadata = getattr(result, "metadata", {}) or {}
    dedupe = metadata.get("deduplication_result")
    groups = dedupe.get("event_groups") if isinstance(dedupe, dict) else []
    if not groups:
        return 0.0
    duplicate_groups = [group for group in groups if isinstance(group, dict) and len(group.get("item_ids") or []) > 1]
    return round(len(duplicate_groups) / len(groups), 4)


def _feedback_event_from_dict(payload: dict[str, Any]):
    from business.foundation.models.quality_loop import BusinessFeedbackEvent

    return BusinessFeedbackEvent.model_validate(payload)


def _learning_signal_from_dict(payload: dict[str, Any]):
    from business.foundation.models.quality_loop import BusinessLearningSignal

    return BusinessLearningSignal.model_validate(payload)


__all__ = ["PRODUCTIZED_BOARD_STEPS", "ProductizedBoardSteps", "build_productized_board_workflow"]
