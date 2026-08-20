from __future__ import annotations

import pytest

from framework.events.canonical import checksum_for
from framework.harness.side_effects.approval import HarnessSideEffectApprovalRequest
from framework.harness.control_plane.errors import HarnessValidationError
from framework.shared.graph_identity import GraphExecutionIdentity, GraphRunIdentity


CHECKSUM = "sha256:" + "a" * 64


def _request(**overrides: object) -> HarnessSideEffectApprovalRequest:
    values: dict[str, object] = {
        "run_id": "run-approval",
        "graph_id": "research.graph",
        "graph_version": "1",
        "graph_ref": "research.graph@1",
        "graph_checksum": CHECKSUM,
        "node_id": "publish",
        "node_instance_id": "publish:1",
        "activity_id": "activity-publish",
        "attempt": 2,
        "effect_id": "effect-1",
        "candidate_checksum": checksum_for({"candidate": 1}),
        "identity_scope_ref": checksum_for({"scope": "run-approval"}),
        "subject_scope_ref": checksum_for({"subject": "paper-1"}),
        "decision_version": "1",
    }
    values.update(overrides)
    return HarnessSideEffectApprovalRequest(**values)


def test_worker_approval_uses_shared_execution_identity_contract() -> None:
    request = _request()

    identity = GraphExecutionIdentity(
        run_id=request.run_id,
        graph_id=request.graph_id,
        graph_version=request.graph_version,
        graph_ref=request.graph_ref,
        graph_checksum=request.graph_checksum,
        node_id=request.node_id,
        node_instance_id=request.node_instance_id,
        activity_id=request.activity_id,
        attempt=request.attempt,
    )

    assert identity.to_dict() == {
        key: request.to_dict()[key]
        for key in identity.to_dict()
    }


def test_terminal_approval_uses_shared_run_identity_contract() -> None:
    request = _request(
        node_id=None,
        node_instance_id=None,
        activity_id=None,
        terminal_action="complete_run",
        attempt=1,
    )

    identity = GraphRunIdentity(
        run_id=request.run_id,
        graph_id=request.graph_id,
        graph_version=request.graph_version,
        graph_ref=request.graph_ref,
        graph_checksum=request.graph_checksum,
    )

    assert identity.to_dict() == {
        key: request.to_dict()[key]
        for key in identity.to_dict()
    }


def test_partial_physical_identity_is_rejected() -> None:
    with pytest.raises(HarnessValidationError, match="physical Graph activity fields"):
        _request(activity_id=None)
