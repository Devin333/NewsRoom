from __future__ import annotations

from business.foundation import BusinessQualityCheck, Signal


def check_signal_quality(signal: Signal) -> list[BusinessQualityCheck]:
    checks = [
        BusinessQualityCheck.create(
            "signal_has_canonical_key",
            passed=bool(signal.canonical_key),
            severity="error",
            reason="Signal must have canonical_key.",
        ),
        BusinessQualityCheck.create(
            "signal_has_content_hash",
            passed=bool(signal.content_hash),
            severity="error",
            reason="Signal must have content_hash.",
        ),
        BusinessQualityCheck.create(
            "signal_has_source",
            passed=bool(signal.source.source_name),
            severity="error",
            reason="Signal must preserve source reference.",
            evidence_refs=[signal.source],
        ),
    ]
    if signal.metrics.get("duplicate_reason"):
        checks.append(
            BusinessQualityCheck.create(
                "duplicate_signal",
                passed=False,
                severity="warning",
                reason=str(signal.metrics["duplicate_reason"]),
                evidence_refs=[signal.source],
            )
        )
    return checks
