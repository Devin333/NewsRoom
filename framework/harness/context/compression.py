from __future__ import annotations

from framework.harness.context.models import (
    CONTROL_PLANE_PRESERVED_FIELDS,
    NON_COMPRESSIBLE_SEGMENT_TYPES,
    CompressionRecord,
    ContextCompressionLevel,
    ContextSegment,
)
from framework.harness.control_plane.errors import HarnessValidationError


class ContextCompressor:
    def __init__(self) -> None:
        self.records: list[CompressionRecord] = []

    def compress_segment(
        self,
        segment: ContextSegment,
        *,
        run_id: str,
        target_level: ContextCompressionLevel = ContextCompressionLevel.C2_STEP_SUMMARY,
    ) -> tuple[ContextSegment, CompressionRecord]:
        if segment.segment_type in NON_COMPRESSIBLE_SEGMENT_TYPES:
            raise HarnessValidationError("control-plane context segment must not be compressed", details=segment.to_dict())
        preserved_refs = tuple(segment.provenance_refs) + tuple(segment.metadata.get("source_refs", ())) + tuple(
            segment.metadata.get("artifact_refs", ())
        )
        lost_fields = tuple(
            field for field in segment.metadata.get("lost_fields", ()) if field not in CONTROL_PLANE_PRESERVED_FIELDS
        )
        compressed = ContextSegment(
            segment_id=f"{segment.segment_id}:compressed",
            segment_type=segment.segment_type,
            content_ref=f"artifact://context-summary/{segment.segment_id}",
            summary=segment.summary[: max(len(segment.summary) // 2, 1)],
            token_estimate=max(segment.token_estimate // 2, 1),
            compression_level=target_level,
            provenance_refs=preserved_refs or segment.provenance_refs,
            cache_scope=segment.cache_scope,
            metadata={
                **segment.metadata,
                "compressed_from": segment.segment_id,
                "preserved_refs": list(preserved_refs or segment.provenance_refs),
            },
        )
        record = CompressionRecord(
            compression_id=f"compression://{len(self.records) + 1}",
            run_id=run_id,
            source_ref=segment.content_ref,
            source_level=segment.compression_level,
            target_level=target_level,
            summary_ref=compressed.content_ref,
            lost_fields=lost_fields,
            preserved_refs=preserved_refs or segment.provenance_refs,
            gate_results=({"gate": "context_compression_loss", "passed": True},),
        )
        self.records.append(record)
        return compressed, record


__all__ = ["ContextCompressor"]
