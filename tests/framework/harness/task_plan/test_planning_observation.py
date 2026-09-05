from __future__ import annotations

import pytest

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.task_plan.planning_observation import (
    HarnessPlanningObservationService,
    InMemoryPlanningObservationStore,
    JsonlPlanningObservationStore,
    PlanningObservationPolicy,
    PlanningObservationRequest,
)
from framework.tool import ToolDefinition, ToolExecutor, ToolRegistry, ToolSideEffect, ToolStatus


def _service(*, tool_name: str = "research.lookup", side_effect: str = "read_only"):
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name=tool_name,
            version="1.0.0",
            side_effect=side_effect,
            concurrency_safe=True,
            input_schema={"type": "object"},
        ),
        lambda arguments: {"answer": arguments["query"]},
    )
    store = InMemoryPlanningObservationStore()
    policy = PlanningObservationPolicy(
        policy_checksum="sha256:" + "1" * 64,
        allowed_tool_ids=(f"{tool_name}@1.0.0",),
        max_tool_calls=1,
        timeout_seconds=2,
    )
    return (
        HarnessPlanningObservationService(
            executor=ToolExecutor(registry),
            registry=registry,
            store=store,
            policy=policy,
        ),
        store,
        policy,
    )


def _request(policy_checksum: str, *, tool_name: str = "research.lookup") -> PlanningObservationRequest:
    return PlanningObservationRequest(
        request_id="planning-request-1",
        run_id="run-1",
        stage_id="stage-1",
        planner_turn_id="turn-1",
        policy_checksum=policy_checksum,
        correlation_id="corr-1",
        tool_name=tool_name,
        purpose="look up a read-only fact",
        arguments={"query": "paper"},
    )


def test_planning_observation_persists_receipt_and_replay_never_executes() -> None:
    service, store, policy = _service()
    request = _request(policy.policy_checksum)
    receipt = service.observe(request)
    assert receipt.status == "SUCCEEDED"
    assert receipt.source_ref.startswith("planning-observation://")
    assert store.by_request(request.request_checksum) == receipt

    class _ExplodingExecutor:
        def execute(self, *_args, **_kwargs):
            raise AssertionError("replay must not invoke a live tool")

    service._executor = _ExplodingExecutor()  # type: ignore[attr-defined]
    assert service.replay(request) == receipt


def test_planning_observation_denies_unallowlisted_and_side_effect_tools_before_execution() -> None:
    service, _store, policy = _service(tool_name="research.write", side_effect="writes_local_state")
    receipt = service.observe(_request(policy.policy_checksum, tool_name="research.write"))
    assert receipt.status == "REJECTED"
    assert receipt.reason_code == "planning_tool_not_read_only"

    service, _store, policy = _service()
    request = _request(policy.policy_checksum, tool_name="research.unknown")
    receipt = service.observe(request)
    assert receipt.status == "REJECTED"
    assert receipt.reason_code == "planning_tool_unavailable"


def test_planning_observation_enforces_policy_scope_and_budget() -> None:
    service, store, policy = _service()
    request = _request(policy.policy_checksum)
    receipt = service.observe(request)
    assert service.observe(request) == receipt

    second = PlanningObservationRequest(
        request_id="planning-request-2",
        run_id=request.run_id,
        stage_id=request.stage_id,
        planner_turn_id=request.planner_turn_id,
        policy_checksum=request.policy_checksum,
        correlation_id="corr-2",
        tool_name=request.tool_name,
        purpose=request.purpose,
        arguments=request.arguments,
    )
    denied = service.observe(second)
    assert denied.status == "REJECTED"
    assert denied.reason_code == "planning_tool_budget_exhausted"

    with pytest.raises(HarnessValidationError, match="outside candidate scope"):
        service.validate_source_refs(
            (receipt.source_ref,),
            run_id="other-run",
            stage_id=request.stage_id,
            planner_turn_id=request.planner_turn_id,
            policy_checksum=policy.policy_checksum,
        )


def test_planning_observation_replay_requires_durable_receipt() -> None:
    service, _store, policy = _service()
    with pytest.raises(HarnessValidationError) as exc_info:
        service.replay(_request(policy.policy_checksum))
    assert exc_info.value.code == "planning_observation_receipt_missing"


def test_planning_observation_policy_defaults_to_denied() -> None:
    service, _store, _policy = _service()
    denied_policy = PlanningObservationPolicy(
        policy_checksum="sha256:" + "2" * 64,
    )
    service = HarnessPlanningObservationService(
        executor=service._executor,  # type: ignore[attr-defined]
        registry=service._registry,  # type: ignore[attr-defined]
        store=InMemoryPlanningObservationStore(),
        policy=denied_policy,
    )
    receipt = service.observe(_request(denied_policy.policy_checksum))
    assert receipt.status == "REJECTED"
    assert receipt.reason_code == "planning_tool_not_allowlisted"


def test_planning_observation_jsonl_store_restores_integrity_checked_receipt(tmp_path) -> None:
    service, _store, policy = _service()
    receipt = service.observe(_request(policy.policy_checksum))
    path = tmp_path / "planning-receipts.jsonl"
    durable = JsonlPlanningObservationStore(path)
    durable.save(receipt)

    restored = JsonlPlanningObservationStore(path)
    assert restored.by_source_ref(receipt.source_ref) == receipt
