from __future__ import annotations

from datetime import UTC, datetime, timedelta
from dataclasses import replace

import pytest

from framework.events.canonical import PayloadReference, checksum_for
from framework.events.projection import GraphEventContext, GraphEventExecutionVersion
from framework.events.runtime.activities import (
    REPLAY_ACTIVITY_RECORD_CONTENT_TYPE,
    RecordedActivityWrite,
    ReplayActivityDescriptor,
    ReplayActivityKind,
    ReplayActivityOutcome,
    ReplayActivityRecord,
    ReplayActivityStatus,
)
from framework.events.schema.security import SecurityClassification
from framework.harness.control_plane.durable_events import HarnessEventCanonicalAdapter
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.graph_runtime import HarnessGraphActivity
from framework.harness.graph.activity import graph_activity_input_checksum
from framework.harness.graph.model import HarnessContractKind, HarnessContractReference
from framework.harness.graph.reference import HarnessGraphReference
from framework.harness.graph.versioning import (
    GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
    HARNESS_CONDITION_POLICY_VERSION,
    HARNESS_GRAPH_ONLY_COMPILER_VERSION,
)
from framework.shared.graph_identity import GraphExecutionIdentity, GraphRunIdentity


NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def _activity() -> HarnessGraphActivity:
    graph_ref = HarnessGraphReference(
        graph_id="reader.graph",
        schema_version=GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
        compiler_version=HARNESS_GRAPH_ONLY_COMPILER_VERSION,
        condition_policy_version=HARNESS_CONDITION_POLICY_VERSION,
        checksum=checksum_for({"graph": "reader"}),
        graph_ref=HarnessContractReference(
            HarnessContractKind.GRAPH,
            "reader.graph",
            "1",
        ),
    )
    return HarnessGraphActivity(
        run_id="run-reader",
        graph_ref=graph_ref,
        node_id="analyze",
        node_instance_id="hni-analyze-1",
        step_ref=HarnessContractReference(
            HarnessContractKind.STEP,
            "reader.analyze",
            "1",
        ),
        worker_ref=HarnessContractReference(
            HarnessContractKind.WORKER,
            "reader.worker",
            "1",
        ),
        activity_ref=HarnessContractReference(
            HarnessContractKind.ACTIVITY,
            "reader.activity",
            "1",
        ),
        attempt=1,
        input_ref=graph_activity_input_checksum({"source": "paper"}),
        causal_decision_checksum=checksum_for({"decision": "dispatch"}),
        causal_decision_sequence=3,
        fencing_generation=1,
        identity_scope_ref=checksum_for("tenant-a"),
    )


def _recorded(activity: HarnessGraphActivity) -> RecordedActivityWrite:
    input_value = {"source": "paper"}
    input_ref = PayloadReference(
        uri="secure-activity://tenant-a/input",
        expected_checksum=checksum_for(input_value),
        content_type="application/json",
    )
    descriptor = ReplayActivityDescriptor(
        activity_id=activity.activity_id,
        activity_kind=ReplayActivityKind.LLM,
        input_ref=input_ref,
        input_checksum=input_ref.expected_checksum,
        idempotency_key=activity.idempotency_key,
        attempt=activity.attempt,
        contract_version=activity.activity_ref.version,
        handler_version=activity.worker_ref.version,
        accepted_at=NOW,
        tenant_id="tenant-a",
        security_classification=SecurityClassification.CONFIDENTIAL,
    )
    output = {"status": "ok"}
    output_ref = PayloadReference(
        uri="secure-activity://tenant-a/output",
        expected_checksum=checksum_for(output),
        content_type="application/json",
    )
    record = ReplayActivityRecord(
        activity=descriptor,
        outcome=ReplayActivityOutcome(
            activity_id=activity.activity_id,
            status=ReplayActivityStatus.SUCCEEDED,
            started_at=NOW + timedelta(seconds=1),
            completed_at=NOW + timedelta(seconds=2),
            output_ref=output_ref,
            output_checksum=output_ref.expected_checksum,
        ),
    )
    recorded_ref = PayloadReference(
        uri="secure-activity://tenant-a/record",
        expected_checksum=record.record_checksum,
        content_type=REPLAY_ACTIVITY_RECORD_CONTENT_TYPE,
    )
    return RecordedActivityWrite(record=record, recorded_ref=recorded_ref)


def _context(
    activity: HarnessGraphActivity,
    *,
    identity: GraphExecutionIdentity | None = None,
    stage_only: bool = False,
) -> GraphEventContext:
    run_identity = GraphRunIdentity(
        run_id=activity.run_id,
        graph_id=activity.graph_ref.graph_id,
        graph_version=activity.graph_ref.identity_version,
        graph_ref=f"{activity.graph_ref.graph_id}@{activity.graph_ref.identity_version}",
        graph_checksum=activity.graph_ref.checksum,
    )
    if stage_only:
        from framework.shared.graph_identity import GraphStageIdentity

        return GraphEventContext(
            identity=run_identity,
            execution_version=GraphEventExecutionVersion(
                graph_schema_version=activity.graph_ref.schema_version,
                compiler_version=activity.graph_ref.compiler_version,
                normalized_graph_checksum=activity.graph_ref.checksum,
            ),
            stage_identity=GraphStageIdentity(
                **run_identity.to_dict(),
                node_id=activity.node_id,
                node_instance_id=activity.node_instance_id,
            ),
        )
    return GraphEventContext(
        identity=run_identity,
        execution_version=GraphEventExecutionVersion(
            graph_schema_version=activity.graph_ref.schema_version,
            compiler_version=activity.graph_ref.compiler_version,
            normalized_graph_checksum=activity.graph_ref.checksum,
        ),
        execution_identity=identity,
    )


def _expected_identity(activity: HarnessGraphActivity) -> GraphExecutionIdentity:
    return GraphExecutionIdentity(
        run_id=activity.run_id,
        graph_id=activity.graph_ref.graph_id,
        graph_version=activity.graph_ref.identity_version,
        graph_ref=f"{activity.graph_ref.graph_id}@{activity.graph_ref.identity_version}",
        graph_checksum=activity.graph_ref.checksum,
        node_id=activity.node_id,
        node_instance_id=activity.node_instance_id,
        activity_id=activity.activity_id,
        attempt=activity.attempt,
    )


def test_activity_result_request_requires_exact_activity_identity() -> None:
    activity = _activity()
    request = HarnessEventCanonicalAdapter(
        tenant_id="tenant-a",
        activity_security_classification=SecurityClassification.CONFIDENTIAL,
    ).to_graph_activity_result_publish_request(
        activity,
        _recorded(activity),
        graph_context=_context(activity, identity=_expected_identity(activity)),
    )

    assert request.business_context.execution_identity == _expected_identity(activity)


@pytest.mark.parametrize("field", ["node_id", "node_instance_id", "activity_id", "attempt"])
def test_activity_result_request_rejects_mixed_physical_identity(field: str) -> None:
    activity = _activity()
    identity = _expected_identity(activity)
    replacement = "other" if field != "attempt" else 2
    mismatched = replace(identity, **{field: replacement})

    with pytest.raises(HarnessValidationError, match="exact activity identity"):
        HarnessEventCanonicalAdapter(
            tenant_id="tenant-a",
            activity_security_classification=SecurityClassification.CONFIDENTIAL,
        ).to_graph_activity_result_publish_request(
            activity,
            _recorded(activity),
            graph_context=_context(activity, identity=mismatched),
        )


def test_activity_result_request_rejects_stage_only_context() -> None:
    activity = _activity()

    with pytest.raises(HarnessValidationError, match="exact activity identity"):
        HarnessEventCanonicalAdapter(
            tenant_id="tenant-a",
            activity_security_classification=SecurityClassification.CONFIDENTIAL,
        ).to_graph_activity_result_publish_request(
            activity,
            _recorded(activity),
            graph_context=_context(activity, stage_only=True),
        )


def test_graph_event_context_rejects_run_identity_as_execution_identity() -> None:
    activity = _activity()
    run_identity = GraphRunIdentity(
        run_id=activity.run_id,
        graph_id=activity.graph_ref.graph_id,
        graph_version=activity.graph_ref.identity_version,
        graph_ref=f"{activity.graph_ref.graph_id}@{activity.graph_ref.identity_version}",
        graph_checksum=activity.graph_ref.checksum,
    )

    with pytest.raises(TypeError, match="GraphExecutionIdentity"):
        _context(activity, identity=run_identity)  # type: ignore[arg-type]
