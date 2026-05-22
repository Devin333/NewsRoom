from __future__ import annotations

import json
from typing import Any

from business.memory.intelligence_context import IntelligenceMemoryContext
from business.memory.intelligence_recall import IntelligenceMemoryRecallService
from business.memory.report_memory_context import (
    ReportMemoryContextRequest,
    ReportMemoryContextResult,
    ReportMemoryContextService,
)
from framework.llm import LLMClient, LLMRequest, build_openai_compatible_client_from_config
from framework.workflow import StepScopedDataBufferView
from business.foundation.models.source import SourcePipelineMetrics
from business.layers.relation.evidence import EvidenceBundle
from business.boards.cross_board.workflows.daily_intelligence.profiles import PROFILE_LIVE, PROFILE_LIVE_OFFLINE


class ReportWriter:
    def __init__(
        self,
        *,
        llm_client: LLMClient | None = None,
        recall_service: IntelligenceMemoryRecallService | None = None,
        memory_context_service: ReportMemoryContextService | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.memory_context_service = memory_context_service or (
            ReportMemoryContextService(recall_service) if recall_service is not None else None
        )

    def draft_report(self, buffer: StepScopedDataBufferView, profile: str) -> dict[str, Any]:
        request = buffer.read("request")
        evidence_bundle = buffer.read("evidence_bundle")
        source_errors = buffer.read("source_errors")
        source_metrics = buffer.read("source_pipeline_metrics")
        memory_result = self._memory_context(str(request["topic"]))
        memory_context = memory_result.context if memory_result is not None else None
        if profile == PROFILE_LIVE_OFFLINE:
            report = _deterministic_report(request["topic"], evidence_bundle)
            report = _with_memory_metadata(report, memory_result)
            return {
                "report_draft": _with_source_notes(
                    report,
                    evidence_bundle,
                    source_errors,
                    source_metrics,
                ),
                "memory_context": memory_context.to_dict() if memory_context is not None else None,
            }

        llm_client = self.llm_client or build_openai_compatible_client_from_config(
            route_id="daily-intelligence-writer"
        )
        response = llm_client.complete(_report_request(request["topic"], evidence_bundle, memory_context))
        report_draft = (
            _validate_report_payload(response.structured_output)
            if response.structured_output is not None
            else _parse_report_json(response.content or "{}")
        )
        report_draft = _with_memory_metadata(report_draft, memory_result)
        report_draft = _with_source_notes(report_draft, evidence_bundle, source_errors, source_metrics)
        return {
            "report_draft": report_draft,
            "memory_context": memory_context.to_dict() if memory_context is not None else None,
        }

    def _memory_context(self, topic: str) -> ReportMemoryContextResult | None:
        if self.memory_context_service is None:
            return None
        result = self.memory_context_service.build_context(
            ReportMemoryContextRequest(topic=topic, limit=5)
        )
        if result.context.is_empty():
            return None
        return result


def _deterministic_report(topic: str, evidence_bundle: EvidenceBundle) -> dict[str, Any]:
    lead = evidence_bundle.items[0]
    return {
        "title": f"Daily Intelligence: {topic}",
        "sections": [
            {
                "title": "Summary",
                "content": f"{lead.title}: {lead.summary}",
                "sources": [lead.source_url],
            },
            {
                "title": "Source Notes",
                "content": f"Built from {len(evidence_bundle.items)} evidence item(s).",
                "sources": sorted(evidence_bundle.source_urls),
            },
        ],
    }


def _with_source_notes(
    report_draft: dict[str, Any],
    evidence_bundle: EvidenceBundle,
    source_errors: list[Any],
    source_metrics: SourcePipelineMetrics,
) -> dict[str, Any]:
    if not _needs_source_notes(source_errors, source_metrics):
        return report_draft
    sections = [dict(section) for section in report_draft.get("sections", [])]
    if any(str(section.get("title") or "").strip().casefold() == "source notes" for section in sections):
        return report_draft
    source_urls = sorted(evidence_bundle.source_urls)
    if not source_urls:
        return report_draft
    error_types = sorted(
        {
            error.error_type if hasattr(error, "error_type") else str(error.get("error_type", "unknown"))
            for error in source_errors
        }
    )
    content_parts = [
        (
            f"Source collection was partial: {source_metrics.sources_failed} source(s) failed "
            f"and {source_metrics.sources_skipped} source(s) were skipped."
        )
    ]
    if error_types:
        content_parts.append(f"Observed source error types: {', '.join(error_types)}.")
    sections.append(
        {
            "title": "Source Notes",
            "content": " ".join(content_parts),
            "sources": source_urls,
        }
    )
    updated = dict(report_draft)
    updated["sections"] = sections
    return updated


def _needs_source_notes(source_errors: list[Any], source_metrics: SourcePipelineMetrics) -> bool:
    if source_metrics.sources_failed > 0 or source_metrics.sources_skipped > 0:
        return True
    return bool(source_errors)


def _report_request(
    topic: str,
    evidence_bundle: EvidenceBundle,
    memory_context: IntelligenceMemoryContext | None = None,
) -> LLMRequest:
    evidence_payload = [item.to_dict() for item in evidence_bundle.items]
    memory_prompt = memory_context.to_prompt_context(limit=5) if memory_context is not None else ""
    user = (
        "Create a concise daily intelligence report as JSON with keys title and sections. "
        "Each section must include title, content, and sources. "
        "Only cite source URLs present in the evidence. "
        f"Topic: {topic}. Evidence: {json.dumps(evidence_payload, ensure_ascii=False)}"
    )
    if memory_prompt:
        user += (
            " Historical memory context is for background and conflict awareness only; "
            "do not cite it as new evidence. "
            f"Memory context: {memory_prompt}"
        )
    return LLMRequest(
        messages=[
            {"role": "system", "content": "You write source-grounded intelligence reports."},
            {"role": "user", "content": user},
        ],
        metadata={
            "profile": PROFILE_LIVE,
            "memory_context_used": memory_context is not None,
            "memory_context": memory_context.to_dict() if memory_context is not None else None,
        },
        response_format="json_object",
    )


def _parse_report_json(content: str) -> dict[str, Any]:
    clean = content.strip()
    if clean.startswith("```"):
        clean = clean.strip("`")
        if clean.startswith("json"):
            clean = clean[4:]
    payload = json.loads(clean)
    return _validate_report_payload(payload)


def _validate_report_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("LLM report output must be a JSON object")
    if "title" not in payload or "sections" not in payload:
        raise ValueError("LLM report output must include title and sections")
    return payload


def _with_memory_metadata(
    report_draft: dict[str, Any],
    memory_result: ReportMemoryContextResult | None,
) -> dict[str, Any]:
    if memory_result is None:
        return report_draft
    updated = dict(report_draft)
    metadata = dict(updated.get("metadata") or {})
    metadata["memory_context_used"] = True
    metadata["memory_context"] = memory_result.context.to_dict()
    metadata["memory_prompt_context"] = memory_result.prompt_context
    updated["metadata"] = metadata
    return updated



