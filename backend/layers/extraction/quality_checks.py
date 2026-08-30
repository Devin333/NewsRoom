from __future__ import annotations

from backend.foundation import BusinessQualityCheck
from backend.layers.extraction.models import ExtractionResult


def check_extraction_quality(result: ExtractionResult) -> list[BusinessQualityCheck]:
    object_count = len(result.entities) + len(result.topics) + len(result.technologies) + len(result.claims)
    return [
        BusinessQualityCheck.create(
            "extraction_has_objects",
            passed=object_count > 0,
            severity="warning",
            reason="Extraction should produce at least one structured object.",
            observed={"object_count": object_count},
        ),
        BusinessQualityCheck.create(
            "claims_have_confidence",
            passed=all(claim.confidence is not None for claim in result.claims),
            severity="error",
            reason="All extracted claims must preserve confidence.",
            observed={"claim_count": len(result.claims)},
        ),
    ]
