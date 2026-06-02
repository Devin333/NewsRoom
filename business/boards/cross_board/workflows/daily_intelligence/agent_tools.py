from __future__ import annotations

from typing import Any

from framework.tool import ToolRegistry
from framework.tool.models import ToolDefinition
from business.foundation.models.source import Lineage
from business.layers.analysis.quality.citation_checker import CitationChecker
from business.layers.relation.evidence.models import EvidenceBundle, EvidenceItem, VerifiedFindings


def build_daily_agent_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="daily.evidence_search",
            description="Search the provided daily evidence bundle without leaving the source boundary.",
            input_schema={
                "type": "object",
                "required": ["evidence_bundle"],
                "properties": {
                    "evidence_bundle": {"type": "object"},
                    "query": {"type": "string"},
                    "evidence_id": {"type": "string"},
                    "source_id": {"type": "string"},
                    "source_url": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 25},
                },
                "additionalProperties": False,
            },
            side_effect="read_only",
            concurrency_safe=True,
            max_result_bytes=100_000,
        ),
        _search_evidence,
    )
    registry.register(
        ToolDefinition(
            name="daily.source_metadata",
            description="Summarize source metadata from the provided daily evidence bundle.",
            input_schema={
                "type": "object",
                "required": ["evidence_bundle"],
                "properties": {
                    "evidence_bundle": {"type": "object"},
                    "source_id": {"type": "string"},
                    "source_url": {"type": "string"},
                },
                "additionalProperties": False,
            },
            side_effect="read_only",
            concurrency_safe=True,
            max_result_bytes=100_000,
        ),
        _source_metadata,
    )
    registry.register(
        ToolDefinition(
            name="daily.citation_validate",
            description="Validate report citations against the provided daily evidence bundle.",
            input_schema={
                "type": "object",
                "required": ["report", "evidence_bundle"],
                "properties": {
                    "report": {"type": "object"},
                    "evidence_bundle": {"type": "object"},
                    "verified_findings": {"type": "object"},
                },
                "additionalProperties": False,
            },
            side_effect="read_only",
            concurrency_safe=True,
            max_result_bytes=200_000,
        ),
        _validate_citations,
    )
    registry.register(
        ToolDefinition(
            name="daily.section_draft",
            description=(
                "Build a source-bounded report section skeleton from the provided daily "
                "evidence bundle."
            ),
            input_schema={
                "type": "object",
                "required": ["evidence_bundle", "title"],
                "properties": {
                    "evidence_bundle": {"type": "object"},
                    "title": {"type": "string"},
                    "section_id": {"type": "string"},
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "additionalProperties": False,
            },
            side_effect="read_only",
            concurrency_safe=True,
            max_result_bytes=120_000,
        ),
        _build_section_draft,
    )
    return registry


def _search_evidence(args: dict[str, Any]) -> dict[str, Any]:
    bundle = _evidence_bundle(args["evidence_bundle"])
    query = str(args.get("query") or "").strip().casefold()
    evidence_id = _optional_string(args.get("evidence_id"))
    source_id = _optional_string(args.get("source_id"))
    source_url = _optional_string(args.get("source_url"))
    limit = max(1, min(25, int(args.get("limit") or 8)))
    matches = _matching_evidence(
        bundle,
        query=query,
        evidence_id=evidence_id,
        source_id=source_id,
        source_url=source_url,
    )
    limited = matches[:limit]
    return {
        "bundle_id": bundle.bundle_id,
        "query": query or None,
        "matched_count": len(matches),
        "returned_count": len(limited),
        "items": [_evidence_item_summary(item) for item in limited],
    }


def _source_metadata(args: dict[str, Any]) -> dict[str, Any]:
    bundle = _evidence_bundle(args["evidence_bundle"])
    source_id = _optional_string(args.get("source_id"))
    source_url = _optional_string(args.get("source_url"))
    rows = []
    for item in bundle.items:
        if source_id and item.source_id != source_id:
            continue
        if source_url and source_url not in item.source_urls:
            continue
        rows.append(
            {
                "evidence_id": item.evidence_id,
                "source_id": item.source_id,
                "source_item_id": item.source_item_id,
                "source_urls": list(item.source_urls),
                "source_reliability": item.source_reliability,
                "confidence": item.confidence,
                "publishable": item.publishable,
                "evidence_type": item.evidence_type,
                "metadata": dict(item.metadata),
            }
        )
    return {
        "bundle_id": bundle.bundle_id,
        "source_count": len({row["source_id"] for row in rows if row["source_id"]}),
        "source_url_count": len({url for row in rows for url in row["source_urls"]}),
        "item_count": len(rows),
        "items": rows,
    }


def _validate_citations(args: dict[str, Any]) -> dict[str, Any]:
    report = args["report"]
    if not isinstance(report, dict):
        raise ValueError("report must be an object")
    result = CitationChecker().check(
        report,
        _evidence_bundle(args["evidence_bundle"]),
        _verified_findings(args.get("verified_findings")),
    )
    return result.to_dict()


def _build_section_draft(args: dict[str, Any]) -> dict[str, Any]:
    bundle = _evidence_bundle(args["evidence_bundle"])
    title = str(args.get("title") or "").strip()
    if not title:
        raise ValueError("title is required")
    section_id = _optional_string(args.get("section_id")) or _section_id(title)
    query = str(args.get("query") or title).strip().casefold()
    limit = max(1, min(10, int(args.get("limit") or 5)))
    items = _matching_evidence(
        bundle,
        query=query,
        evidence_id=None,
        source_id=None,
        source_url=None,
    )[:limit]
    sources = _dedupe_text([url for item in items for url in item.source_urls])
    evidence_ids = _dedupe_text([item.evidence_id for item in items if item.evidence_id])
    claim_grounding = [
        {
            "claim_id": f"{section_id}_claim_{index}",
            "text": _claim_text_from_evidence(item),
            "evidence_ids": [item.evidence_id] if item.evidence_id else [],
            "source_urls": list(item.source_urls),
        }
        for index, item in enumerate(items, start=1)
    ]
    return {
        "bundle_id": bundle.bundle_id,
        "matched_count": len(items),
        "section": {
            "section_id": section_id,
            "title": title,
            "content": " ".join(claim["text"] for claim in claim_grounding),
            "sources": sources,
            "evidence_ids": evidence_ids,
            "claim_grounding": claim_grounding,
        },
        "supporting_items": [_evidence_item_summary(item) for item in items],
    }


def _evidence_bundle(payload: Any) -> EvidenceBundle:
    if isinstance(payload, EvidenceBundle):
        return payload
    if not isinstance(payload, dict):
        raise ValueError("evidence_bundle must be an object")
    items = payload.get("items") or []
    if not isinstance(items, list):
        raise ValueError("evidence_bundle.items must be a list")
    return EvidenceBundle(
        bundle_id=str(payload.get("bundle_id") or "daily-agent-evidence"),
        topic=str(payload.get("topic") or ""),
        items=[_evidence_item(item) for item in items],
        source_map={
            str(key): [str(source_item) for source_item in source_items]
            for key, source_items in dict(payload.get("source_map") or {}).items()
        },
        missing_information=[str(item) for item in payload.get("missing_information") or []],
        coverage_notes=[str(item) for item in payload.get("coverage_notes") or []],
        source_coverage=dict(payload.get("source_coverage") or {}),
        metadata=dict(payload.get("metadata") or {}),
    )


def _evidence_item(payload: Any) -> EvidenceItem:
    if isinstance(payload, EvidenceItem):
        return payload
    if not isinstance(payload, dict):
        raise ValueError("evidence item must be an object")
    source_url = str(payload.get("source_url") or "")
    source_id = str(payload.get("source_id") or "")
    source_item_id = _optional_string(payload.get("source_item_id"))
    return EvidenceItem(
        evidence_id=str(payload.get("evidence_id") or ""),
        source_url=source_url,
        source_urls=[str(url) for url in payload.get("source_urls") or [] if url],
        title=str(payload.get("title") or ""),
        summary=str(payload.get("summary") or payload.get("title") or ""),
        confidence=float(payload.get("confidence") or 0.0),
        source_id=source_id,
        source_item_id=source_item_id,
        source_item_ids=[str(value) for value in payload.get("source_item_ids") or [] if value],
        source_reliability=_optional_string(payload.get("source_reliability")),
        publishable=bool(payload.get("publishable", True)),
        evidence_type=str(payload.get("evidence_type") or "other"),
        lineage=_lineage_from_payload(payload.get("lineage")),
        metadata=dict(payload.get("metadata") or {}),
    )


def _verified_findings(payload: Any) -> VerifiedFindings | None:
    if isinstance(payload, VerifiedFindings):
        return payload
    return None


def _matching_evidence(
    bundle: EvidenceBundle,
    *,
    query: str,
    evidence_id: str | None,
    source_id: str | None,
    source_url: str | None,
) -> list[EvidenceItem]:
    matches = []
    for item in bundle.items:
        if evidence_id and item.evidence_id != evidence_id:
            continue
        if source_id and item.source_id != source_id:
            continue
        if source_url and source_url not in item.source_urls:
            continue
        haystack = " ".join(
            [
                item.evidence_id,
                item.title,
                item.summary,
                item.source_id,
                *item.source_urls,
            ]
        ).casefold()
        if query and query not in haystack:
            continue
        matches.append(item)
    return matches


def _lineage_from_payload(payload: Any) -> Lineage | None:
    if isinstance(payload, Lineage):
        return payload
    if isinstance(payload, dict):
        try:
            return Lineage.from_dict(payload)
        except Exception:
            return None
    return None


def _evidence_item_summary(item: EvidenceItem) -> dict[str, Any]:
    return {
        "evidence_id": item.evidence_id,
        "title": item.title,
        "summary": item.summary,
        "source_id": item.source_id,
        "source_item_id": item.source_item_id,
        "source_urls": list(item.source_urls),
        "confidence": item.confidence,
        "source_reliability": item.source_reliability,
        "publishable": item.publishable,
        "metadata": dict(item.metadata),
    }


def _claim_text_from_evidence(item: EvidenceItem) -> str:
    return item.summary or item.title


def _section_id(title: str) -> str:
    normalized = "_".join(str(title).casefold().split())
    return "".join(character for character in normalized if character.isalnum() or character == "_") or "section"


def _dedupe_text(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
