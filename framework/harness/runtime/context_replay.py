from __future__ import annotations

from framework.harness.context.models import CompressionRecord, ContextSnapshot
from framework.harness.control_plane.errors import HarnessValidationError


class ContextSnapshotReplayReader:
    def replay_snapshot(self, snapshot: ContextSnapshot) -> dict:
        if not snapshot.refs:
            raise HarnessValidationError("context snapshot replay requires refs")
        if not str(snapshot.checksum).startswith("sha256:"):
            raise HarnessValidationError("context snapshot checksum is invalid")
        return {
            "snapshot_id": snapshot.snapshot_id,
            "envelope_id": snapshot.envelope_id,
            "refs": list(snapshot.refs),
            "segment_refs": list(snapshot.segment_refs),
            "assembled_prompt_ref": snapshot.assembled_prompt_ref,
            "token_estimate": snapshot.token_estimate,
            "cache_key": snapshot.cache_key,
            "checksum": snapshot.checksum,
            "side_effects_replayed": False,
        }


class CompressionRecordReplayReader:
    def replay_record(self, record: CompressionRecord) -> dict:
        if not record.preserved_refs:
            raise HarnessValidationError("compression replay requires preserved refs")
        if record.metadata.get("checksum") and not str(record.metadata["checksum"]).startswith("sha256:"):
            raise HarnessValidationError("compression record checksum is invalid")
        return {
            "compression_id": record.compression_id,
            "run_id": record.run_id,
            "source_ref": record.source_ref,
            "source_level": record.source_level.value,
            "target_level": record.target_level.value,
            "summary_ref": record.summary_ref,
            "preserved_refs": list(record.preserved_refs),
            "gate_results": list(record.gate_results),
            "side_effects_replayed": False,
        }


__all__ = ["CompressionRecordReplayReader", "ContextSnapshotReplayReader"]
