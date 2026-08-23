from __future__ import annotations

import json
import inspect
from pathlib import Path

import pytest

from framework.agent.loop.runner import AgentRunner
from framework.agent.models import AgentSpec
from framework.events.canonical import checksum_for
from framework.harness.agent_loop import AGENT_LOOP_GRAPH_ACTIVITY_TASK_SCHEMA
from framework.harness.control_plane.activity_execution import (
    HarnessGraphActivityExecutionInput,
)
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.graph_runtime import HarnessGraphActivity
from framework.harness.graph import (
    GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
    HARNESS_CONDITION_POLICY_VERSION,
    HARNESS_GRAPH_ONLY_COMPILER_VERSION,
    HarnessContractKind,
    HarnessContractReference,
    HarnessLeafActivityKind,
    graph_activity_input_checksum,
)
from framework.harness.graph.bindings import HarnessActivityUsage
from framework.harness.graph.reference import HarnessGraphReference
from framework.llm import FakeLLMClient
from framework.tool import ToolRegistry
from infrastructure.research.artifact_port import FilesystemHarnessArtifactPort
from infrastructure.storage.conversation import LocalJsonConversationStore
from infrastructure.storage.harness import SQLiteHarnessNodeOutputResource
from interfaces.composition.agent_loop_graph import (
    build_agent_loop_graph_application_service,
)
from interfaces.services.agent_loop_graph_service import (
    AgentLoopGraphApplicationService,
    SQLiteAgentLoopActivityResultStore,
)
from framework.harness.control_plane.graph_state import HarnessNodeInstanceIdentity


WORKER_REF = HarnessContractReference(
    HarnessContractKind.WORKER, "production.agent-loop", "1"
)
ACTIVITY_REF = HarnessContractReference(
    HarnessContractKind.ACTIVITY, "production.agent-loop", "1"
)
GRAPH_REF = HarnessGraphReference(
    graph_id="production.agent-loop.graph",
    graph_ref=HarnessContractReference(
        HarnessContractKind.GRAPH, "production.agent-loop.graph", "1"
    ),
    schema_version=GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
    compiler_version=HARNESS_GRAPH_ONLY_COMPILER_VERSION,
    condition_policy_version=HARNESS_CONDITION_POLICY_VERSION,
    checksum=checksum_for({"graph": "production.agent-loop.graph", "version": "1"}),
)


def _runner(root: Path, topic: str) -> AgentRunner:
    return AgentRunner(
        llm_client=FakeLLMClient(
            [
                json.dumps(
                    {
                        "action_type": "final_output",
                        "output": {"analysis_result": {"topic": topic}},
                    }
                )
            ]
        ),
        tool_registry=ToolRegistry(),
        conversation_store=LocalJsonConversationStore(root / "conversation"),
    )


def _agent() -> AgentSpec:
    return AgentSpec(
        agent_id="production-agent",
        name="Production Agent",
        role="Analyst",
        goal="Produce one bounded result",
        instructions="Return one JSON result.",
        output_key="analysis_result",
    )


def _activity_and_input(run_id: str, *, leaf_kind=HarnessLeafActivityKind.AGENT_LOOP):
    task = {
        "schema_version": AGENT_LOOP_GRAPH_ACTIVITY_TASK_SCHEMA,
        "inputs": {"topic": "recovery-topic"},
        "conversation_id": f"{run_id}-conversation",
        "resume_from_cursor": False,
    }
    identity = HarnessNodeInstanceIdentity(
        run_id=run_id,
        graph_checksum=GRAPH_REF.checksum,
        node_id="run-agent-loop",
        activation_ordinal=1,
    )
    activity = HarnessGraphActivity(
        run_id=run_id,
        graph_ref=GRAPH_REF,
        node_id="run-agent-loop",
        node_instance_id=identity.instance_id,
        step_ref=HarnessContractReference(HarnessContractKind.STEP, "run-agent-loop", "1"),
        worker_ref=WORKER_REF,
        activity_ref=ACTIVITY_REF,
        attempt=1,
        input_ref=graph_activity_input_checksum(task),
        causal_decision_checksum=checksum_for({"decision": "dispatch", "run_id": run_id}),
        causal_decision_sequence=1,
        fencing_generation=1,
        tenant_scope_ref=checksum_for({"tenant": "production"}),
        identity_scope_ref=checksum_for({"run": run_id}),
        subject_scope_ref=checksum_for({"topic": "recovery-topic"}),
    )
    execution_input = HarnessGraphActivityExecutionInput.for_activity(
        activity,
        task=task,
        leaf_activity_kind=leaf_kind,
        required_usage=HarnessActivityUsage.SERIAL,
        graph_checkpoint_ref=f"graph-state://{run_id}/checkpoint",
        output_keys=("agent_loop_result",),
    )
    return activity, execution_input


def _service(tmp_path: Path) -> AgentLoopGraphApplicationService:
    root = tmp_path / "artifacts"
    return build_agent_loop_graph_application_service(
        agent_runner=_runner(root, "recovery-topic"),
        artifact_port=FilesystemHarnessArtifactPort(root),
        node_output_resource=SQLiteHarnessNodeOutputResource(root / "node.sqlite3"),
        result_committer=SQLiteAgentLoopActivityResultStore(root / "results.sqlite3"),
        worker_ref=WORKER_REF,
        activity_ref=ACTIVITY_REF,
    )


def test_composition_factory_requires_explicit_durable_ports(tmp_path: Path) -> None:
    signature = inspect.signature(build_agent_loop_graph_application_service)
    assert all(
        parameter.default is inspect.Parameter.empty
        for parameter in signature.parameters.values()
    )
    service = _service(tmp_path)
    assert isinstance(service, AgentLoopGraphApplicationService)


def test_service_executes_and_recovers_without_second_worker_call(tmp_path: Path) -> None:
    service = _service(tmp_path)
    activity, execution_input = _activity_and_input("agent-loop-production-1")
    first = service.execute(
        activity=activity,
        execution_input=execution_input,
        agent=_agent(),
        attempt_id="agent-loop-production-1-attempt-1",
    )
    assert first.node_output_commit is not None
    second = service.execute(
        activity=activity,
        execution_input=execution_input,
        agent=_agent(),
    )
    assert second.recovered_output is True
    assert second.node_output_commit == first.node_output_commit
    assert second.graph_result == first.graph_result


def test_service_rejects_non_agent_loop_leaf_before_worker(tmp_path: Path) -> None:
    service = _service(tmp_path)
    activity, execution_input = _activity_and_input(
        "agent-loop-production-invalid",
        leaf_kind=HarnessLeafActivityKind.FUNCTION,
    )
    with pytest.raises(HarnessValidationError, match="agent_loop"):
        service.execute(
            activity=activity,
            execution_input=execution_input,
            agent=_agent(),
        )
