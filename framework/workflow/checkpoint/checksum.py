"""Checkpoint checksum helpers."""

from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256
from typing import Any

from framework.workflow.checkpoint.envelope import WorkflowCheckpointEnvelope

__all__ = [
    "attach_checkpoint_checksum",
    "checkpoint_checksum_payload",
    "compute_checkpoint_checksum",
    "stable_json_dumps",
    "verify_checkpoint_checksum",
]


def checkpoint_checksum_payload(envelope: WorkflowCheckpointEnvelope) -> dict[str, Any]:
    metadata = _metadata_checksum_payload(envelope.metadata)
    return {
        "checkpoint_id": envelope.checkpoint_id,
        "schema_version": envelope.schema_version,
        "run_id": envelope.run_id,
        "workflow_id": envelope.workflow_id,
        "workflow_version": envelope.workflow_version,
        "current_step_ids": list(envelope.current_step_ids),
        "data_buffer_snapshot": envelope.data_buffer_snapshot,
        "step_results": envelope.step_results,
        "path": list(envelope.path),
        "manifest_hash": envelope.manifest_hash,
        "created_at": envelope.created_at,
        "metadata": metadata,
    }


def stable_json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def compute_checkpoint_checksum(payload: dict[str, Any]) -> str:
    return sha256(stable_json_dumps(payload).encode("utf-8")).hexdigest()


def attach_checkpoint_checksum(
    envelope: WorkflowCheckpointEnvelope,
) -> WorkflowCheckpointEnvelope:
    checksum = compute_checkpoint_checksum(checkpoint_checksum_payload(envelope))
    return replace(envelope, checksum=checksum)


def verify_checkpoint_checksum(envelope: WorkflowCheckpointEnvelope) -> bool:
    expected = compute_checkpoint_checksum(checkpoint_checksum_payload(envelope))
    return envelope.checksum == expected


def _metadata_checksum_payload(metadata: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    protected = metadata.get("protected")
    if isinstance(protected, dict):
        payload["protected"] = dict(protected)
    return payload
