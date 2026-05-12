from __future__ import annotations

from typing import Any

from core.framework.tools.models import ToolDefinition
from core.framework.tools.registry import ToolRegistry
from evidence.models import EvidenceBundle, EvidenceItem
from quality import CitationChecker


def register_quality_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolDefinition(
            name="quality.citation_check",
            description="Check report citations against an evidence bundle.",
            input_schema={
                "required": ["report", "evidence_bundle"],
                "properties": {
                    "report": {"type": "object"},
                    "evidence_bundle": {"type": "object"},
                },
                "additionalProperties": False,
            },
            side_effect="read_only",
            concurrency_safe=True,
        ),
        _citation_check,
    )


def _citation_check(args: dict[str, Any]) -> dict[str, Any]:
    return CitationChecker().check(
        dict(args["report"]),
        _evidence_bundle(args["evidence_bundle"]),
    ).to_dict()


def _evidence_bundle(payload: Any) -> EvidenceBundle:
    if not isinstance(payload, dict):
        raise ValueError("evidence_bundle must be an object")
    items = payload.get("items") or []
    if not isinstance(items, list):
        raise ValueError("evidence_bundle.items must be a list")
    return EvidenceBundle(
        bundle_id=str(payload.get("bundle_id") or "tool-evidence-bundle"),
        items=[_evidence_item(item) for item in items],
        source_map={key: list(value) for key, value in dict(payload.get("source_map") or {}).items()},
        missing_information=list(payload.get("missing_information") or []),
        coverage_notes=list(payload.get("coverage_notes") or []),
        metadata=dict(payload.get("metadata") or {}),
    )


def _evidence_item(payload: Any) -> EvidenceItem:
    if not isinstance(payload, dict):
        raise ValueError("evidence item must be an object")
    return EvidenceItem(
        evidence_id=str(payload.get("evidence_id") or ""),
        source_url=str(payload.get("source_url") or ""),
        title=str(payload.get("title") or ""),
        summary=str(payload.get("summary") or ""),
        confidence=float(payload.get("confidence", 0.0)),
        source_id=str(payload.get("source_id") or ""),
        metadata=dict(payload.get("metadata") or {}),
    )
