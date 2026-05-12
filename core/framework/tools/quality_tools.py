from __future__ import annotations

from typing import Any

from core.framework.tools.models import ToolDefinition
from core.framework.tools.registry import ToolRegistry
from evidence.models import EvidenceBundle, EvidenceItem
from quality import CitationChecker, EditorGate, QualityScorer, SupportMatrixBuilder
from sources.processing.normalize import canonicalize_url, normalize_text


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
    registry.register(
        ToolDefinition(
            name="quality.duplicate_check",
            description="Detect duplicate source or evidence items by canonical URL and title.",
            input_schema={
                "required": ["items"],
                "properties": {"items": {"type": "array"}},
                "additionalProperties": False,
            },
            side_effect="read_only",
            concurrency_safe=True,
        ),
        _duplicate_check,
    )
    registry.register(
        ToolDefinition(
            name="quality.claim_support_check",
            description="Check report section support against an evidence bundle.",
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
        _claim_support_check,
    )
    registry.register(
        ToolDefinition(
            name="quality.editor_score",
            description="Run deterministic quality scoring and editor gate review.",
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
        _editor_score,
    )


def _citation_check(args: dict[str, Any]) -> dict[str, Any]:
    return CitationChecker().check(
        dict(args["report"]),
        _evidence_bundle(args["evidence_bundle"]),
    ).to_dict()


def _duplicate_check(args: dict[str, Any]) -> dict[str, Any]:
    items = args["items"]
    if not isinstance(items, list):
        raise ValueError("items must be a list")
    duplicate_groups = _duplicate_groups([_item_payload(item) for item in items])
    return {
        "item_count": len(items),
        "duplicate_group_count": len(duplicate_groups),
        "duplicate_item_count": sum(
            max(0, len(group["item_ids"]) - 1) for group in duplicate_groups
        ),
        "duplicate_groups": duplicate_groups,
    }


def _claim_support_check(args: dict[str, Any]) -> dict[str, Any]:
    report = _report_payload(args["report"])
    support_matrix = SupportMatrixBuilder().build(
        report,
        _evidence_bundle(args["evidence_bundle"]),
    )
    unsupported_sections = support_matrix.unsupported_sections
    return {
        **support_matrix.to_dict(),
        "section_count": len(support_matrix.sections),
        "supported_section_count": len(support_matrix.sections) - len(unsupported_sections),
        "unsupported_section_count": len(unsupported_sections),
    }


def _editor_score(args: dict[str, Any]) -> dict[str, Any]:
    report = _report_payload(args["report"])
    evidence_bundle = _evidence_bundle(args["evidence_bundle"])
    citation_check = CitationChecker().check(report, evidence_bundle)
    support_matrix = SupportMatrixBuilder().build(report, evidence_bundle)
    quality_summary = QualityScorer().score(
        report=report,
        citation_check=citation_check,
        support_matrix=support_matrix,
    )
    editor_review = EditorGate().review(
        citation_check,
        support_matrix,
        quality_summary,
    )
    return {
        "passed": editor_review.decision.value == "pass",
        "decision": editor_review.decision.value,
        "quality_score": quality_summary.quality_score,
        "citation_check": citation_check.to_dict(),
        "support_matrix": support_matrix.to_dict(),
        "quality_summary": quality_summary.to_dict(),
        "editor_review": editor_review.to_dict(),
    }


def _duplicate_groups(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parent = list(range(len(items)))
    signatures: dict[tuple[str, str], list[int]] = {}
    for index, item in enumerate(items):
        for reason, signature in _item_signatures(item):
            signatures.setdefault((reason, signature), []).append(index)

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for indexes in signatures.values():
        for index in indexes[1:]:
            union(indexes[0], index)

    component_indexes: dict[int, list[int]] = {}
    component_reasons: dict[int, set[str]] = {}
    for index in range(len(items)):
        component_indexes.setdefault(find(index), []).append(index)
    for (reason, _signature), indexes in signatures.items():
        if len(indexes) < 2:
            continue
        root = find(indexes[0])
        component_reasons.setdefault(root, set()).add(reason)

    groups = []
    for root, indexes in sorted(component_indexes.items(), key=lambda item: item[1][0]):
        if len(indexes) < 2:
            continue
        groups.append(
            {
                "item_ids": [_item_id(items[index], index) for index in indexes],
                "indexes": indexes,
                "reasons": sorted(component_reasons.get(root, set())),
            }
        )
    return groups


def _item_payload(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("each item must be an object")
    return dict(item)


def _item_signatures(item: dict[str, Any]) -> list[tuple[str, str]]:
    signatures: list[tuple[str, str]] = []
    url = str(item.get("url") or item.get("source_url") or "").strip()
    title = str(item.get("title") or "").strip()
    if url:
        signatures.append(("canonical_url", canonicalize_url(url)))
    if title:
        signatures.append(("normalized_title", normalize_text(title)))
    return signatures


def _item_id(item: dict[str, Any], index: int) -> str:
    for key in (
        "item_id",
        "source_item_id",
        "evidence_id",
        "url",
        "source_url",
        "title",
    ):
        value = item.get(key)
        if value:
            return str(value)
    return str(index)


def _report_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("report must be an object")
    sections = payload.get("sections") or []
    if not isinstance(sections, list):
        raise ValueError("report.sections must be a list")
    return dict(payload)


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
