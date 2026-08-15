from __future__ import annotations

from dataclasses import fields

import pytest

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.graph.activity import HarnessStepSpec


def test_activity_contract_contains_only_leaf_lifecycle_fields() -> None:
    assert {item.name for item in fields(HarnessStepSpec)} == {
        "step_id",
        "worker_type",
        "input_keys",
        "output_key",
        "retry_policy",
        "quality_gate",
        "metadata",
        "side_effect_handler",
    }


@pytest.mark.parametrize(
    ("metadata", "expected_path"),
    [
        ({"routing_rules": []}, "metadata.routing_rules"),
        (
            {"scheduler": {"node_readiness": "ready"}},
            "metadata.scheduler.node_readiness",
        ),
        ({"scheduler": {"ready": True}}, "metadata.scheduler.ready"),
        (
            {"governance": [{"publication_decision": "publish"}]},
            "metadata.governance[0].publication_decision",
        ),
        ({"NEXT_STEP": "publish"}, "metadata.NEXT_STEP"),
    ],
)
def test_activity_metadata_rejects_outer_graph_authority(
    metadata: dict[str, object],
    expected_path: str,
) -> None:
    with pytest.raises(HarnessValidationError) as captured:
        HarnessStepSpec("analyze", "llm", metadata=metadata)

    assert captured.value.code == "activity_outer_authority_forbidden"
    assert captured.value.details == {"paths": [expected_path]}


def test_activity_metadata_retains_leaf_contract_configuration() -> None:
    activity = HarnessStepSpec(
        "analyze",
        "llm",
        quality_gate="ResearchAnalysisGate@1",
        side_effect_handler="research.analysis@1",
        metadata={
            "step_version": "2",
            "worker_version": "4",
            "control_fact_paths": ["claim_count"],
            "approval_required": True,
        },
    )

    assert activity.to_dict()["metadata"] == {
        "step_version": "2",
        "worker_version": "4",
        "control_fact_paths": ["claim_count"],
        "approval_required": True,
    }
