from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from framework.events.canonical import checksum_for
from framework.harness import (
    HarnessSideEffectIntent,
    HarnessSideEffectOrigin,
    HarnessWorkerResult,
    HarnessWorkerStatus,
)
from framework.harness.memory import MemoryWriteCandidate

from business.research.domain.reader_repair import (
    READER_REPAIR_NAMESPACE,
    ReaderRepairCase,
    stable_research_id,
)
from business.research.ports.repair_memory import (
    READER_REPAIR_MEMORY_EFFECT_KIND,
    READER_REPAIR_MEMORY_HANDLER_REF,
    READER_REPAIR_MEMORY_SCHEMA_VERSION,
    READER_REPAIR_MEMORY_STEP_ID,
    validate_reader_repair_memory_candidate,
)

def build_reader_repair_memory_worker_result(
    *,
    run_id: str,
    repair_case: ReaderRepairCase,
    strategy_candidate_bundle: Mapping[str, Any],
    identity_scope_ref: str,
    subject_scope_ref: str,
    attempt: int = 1,
    graph_id: str | None = None,
    graph_version: str | None = None,
    graph_ref: str | None = None,
    graph_checksum: str | None = None,
    node_id: str | None = None,
    node_instance_id: str | None = None,
    activity_id: str | None = None,
) -> HarnessWorkerResult:
    """Build a candidate-only Function result and its worker-origin intent."""

    if not isinstance(repair_case, ReaderRepairCase):
        raise TypeError("repair_case must be ReaderRepairCase")
    if not isinstance(strategy_candidate_bundle, Mapping):
        raise TypeError("strategy_candidate_bundle must be an object")
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id is required")
    if repair_case.issue.run_id is not None and repair_case.issue.run_id != run_id:
        raise ValueError("repair case run_id does not match the worker run")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise ValueError("attempt must be a positive integer")
    graph_fields = (
        graph_id,
        graph_version,
        graph_ref,
        graph_checksum,
        node_id,
        node_instance_id,
        activity_id,
    )
    if any(value is None or not str(value).strip() for value in graph_fields):
        raise ValueError("Reader Repair memory worker requires exact Graph activity identity")

    bundle = dict(strategy_candidate_bundle)
    candidate = MemoryWriteCandidate(
        candidate_id=stable_research_id(
            "repair_memory_write",
            repair_case.repair_case_id,
        ),
        namespace=READER_REPAIR_NAMESPACE,
        content={
            "repair_case": repair_case.to_dict(),
            "strategy_candidate_bundle": bundle,
        },
        source_refs=tuple(repair_case.source_refs),
        metadata={
            "active_skill_mutation": False,
            "input_bindings": {
                "reader_repair_case": checksum_for(repair_case.to_dict()),
                "strategy_candidate_bundle": checksum_for(bundle),
            },
        },
    )
    projection = validate_reader_repair_memory_candidate(candidate)
    candidate_ref = (
        f"memory-candidate://{READER_REPAIR_NAMESPACE}/"
        f"{projection.candidate.candidate_id}"
    )
    effect_digest = checksum_for(
        {
            "run_id": run_id,
            "step_id": READER_REPAIR_MEMORY_STEP_ID,
            "attempt": attempt,
            "candidate_checksum": projection.candidate_checksum,
        }
    ).removeprefix("sha256:")
    intent = HarnessSideEffectIntent(
        effect_id=f"reader-repair-memory-effect:{effect_digest}",
        kind=READER_REPAIR_MEMORY_EFFECT_KIND,
        run_id=run_id,
        graph_id=graph_id,
        graph_version=graph_version,
        graph_ref=graph_ref,
        graph_checksum=graph_checksum,
        origin=HarnessSideEffectOrigin.WORKER,
        atomic_group=f"reader-repair-memory:{effect_digest}",
        identity_scope_ref=identity_scope_ref,
        subject_scope_ref=subject_scope_ref,
        attempt=attempt,
        node_id=node_id,
        node_instance_id=node_instance_id,
        activity_id=activity_id,
        step_id=READER_REPAIR_MEMORY_STEP_ID,
        worker_result_ref=(
            f"worker-result-candidate://{run_id}/"
            f"{READER_REPAIR_MEMORY_STEP_ID}/{attempt}"
        ),
        candidate_checksum=projection.candidate_checksum,
        handler=READER_REPAIR_MEMORY_HANDLER_REF,
        payload={
            "schema_version": READER_REPAIR_MEMORY_SCHEMA_VERSION,
            "memory_write_candidate": projection.candidate.to_dict(),
            "memory_candidate_checksum": projection.candidate_checksum,
        },
        candidate_refs=(candidate_ref,),
    )
    return HarnessWorkerResult(
        status=HarnessWorkerStatus.SUCCEEDED,
        output={"memory_write_candidate": projection.candidate.to_dict()},
        effect_intent=intent,
    )


__all__ = [
    "READER_REPAIR_MEMORY_STEP_ID",
    "build_reader_repair_memory_worker_result",
]
