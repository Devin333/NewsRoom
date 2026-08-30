from __future__ import annotations

from typing import Any

from backend.foundation.models.source import RankedSourceItem, SourceTraceabilityIssue, SourceTraceabilityReport


REQUIRED_LINEAGE_FIELDS = (
    "source_id",
    "source_item_id",
    "canonical_url",
    "normalized_item_id",
    "ranked_item_id",
)


def build_source_traceability_report(
    ranked_items: list[RankedSourceItem],
) -> SourceTraceabilityReport:
    rows: list[dict[str, Any]] = []
    issues: list[SourceTraceabilityIssue] = []

    for ranked in ranked_items:
        lineage = ranked.lineage
        actual = {
            "source_id": lineage.source_id if lineage is not None else None,
            "source_item_id": lineage.source_item_id if lineage is not None else None,
            "canonical_url": lineage.canonical_url if lineage is not None else None,
            "normalized_item_id": lineage.normalized_item_id if lineage is not None else None,
            "ranked_item_id": lineage.ranked_item_id if lineage is not None else None,
        }
        expected = {
            "source_id": ranked.item.source_id,
            "source_item_id": ranked.item.source_item_id,
            "canonical_url": ranked.item.canonical_url,
            "normalized_item_id": ranked.item.normalized_item_id,
            "ranked_item_id": ranked.ranked_item_id,
        }
        missing_fields: list[str] = []
        mismatched_fields: list[str] = []

        for field_name in REQUIRED_LINEAGE_FIELDS:
            actual_value = _optional_string(actual[field_name])
            expected_value = _optional_string(expected[field_name])
            if actual_value is None:
                missing_fields.append(field_name)
                issues.append(
                    SourceTraceabilityIssue(
                        ranked_item_id=ranked.ranked_item_id,
                        normalized_item_id=ranked.item.normalized_item_id,
                        source_item_id=ranked.item.source_item_id,
                        source_id=ranked.item.source_id,
                        issue_type="missing_lineage_field",
                        field=field_name,
                        expected=expected_value,
                    )
                )
                continue
            if expected_value is not None and actual_value != expected_value:
                mismatched_fields.append(field_name)
                issues.append(
                    SourceTraceabilityIssue(
                        ranked_item_id=ranked.ranked_item_id,
                        normalized_item_id=ranked.item.normalized_item_id,
                        source_item_id=ranked.item.source_item_id,
                        source_id=ranked.item.source_id,
                        issue_type="mismatched_lineage_field",
                        field=field_name,
                        expected=expected_value,
                        actual=actual_value,
                    )
                )

        traceable = not missing_fields and not mismatched_fields
        rows.append(
            {
                "ranked_item_id": ranked.ranked_item_id,
                "normalized_item_id": ranked.item.normalized_item_id,
                "source_item_id": ranked.item.source_item_id,
                "source_id": ranked.item.source_id,
                "canonical_url": ranked.item.canonical_url,
                "traceable": traceable,
                "missing_fields": missing_fields,
                "mismatched_fields": mismatched_fields,
            }
        )

    traceable_count = sum(1 for row in rows if row["traceable"])
    status = "empty" if not ranked_items else "complete" if not issues else "partial"
    return SourceTraceabilityReport(
        traceability_status=status,
        ranked_item_count=len(ranked_items),
        traceable_item_count=traceable_count,
        untraceable_item_count=len(ranked_items) - traceable_count,
        issue_count=len(issues),
        rows=rows,
        issues=issues,
    )


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
