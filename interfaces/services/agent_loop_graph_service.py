from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from threading import RLock
from typing import Any

from framework.agent.loop.runner import AgentRunner
from framework.agent.models import AgentSpec
from framework.harness.agent_loop import (
    AgentLoopGraphArtifactRecorder,
    build_agent_loop_graph_activity_binding_bundle,
)
from framework.harness.control_plane.activity_execution import (
    HarnessGraphActivityExecutionCommitPort,
    HarnessGraphActivityExecutionInput,
    HarnessGraphActivityExecutionInputResolverPort,
)
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.graph_runtime import (
    HarnessGraphActivity,
    HarnessGraphActivityResult,
)
from framework.harness.control_plane.node_output import (
    HarnessNodeOutputResourcePort,
)
from framework.harness.graph import (
    HarnessContractKind,
    HarnessContractReference,
    HarnessLeafActivityKind,
)
from framework.harness.graph.result_lineage import HarnessGraphResultLineage
from framework.harness.graph.bindings import HarnessActivityUsage
from framework.harness.runtime import HarnessGraphPhysicalActivityExecutionResult
from framework.harness.runtime.activity_executor import (
    HarnessGraphPhysicalActivityExecutor,
)
from framework.harness.workers.result import HarnessWorkerResult
from framework.shared.attempts import AttemptSupervisor
from framework.shared.time import utc_now
from framework.harness.artifacts import RunBoundArtifactPort


class _BoundInputResolver(HarnessGraphActivityExecutionInputResolverPort):
    def __init__(self, execution_input: HarnessGraphActivityExecutionInput) -> None:
        self._execution_input = execution_input

    def resolve_execution_input(
        self,
        activity: HarnessGraphActivity,
    ) -> HarnessGraphActivityExecutionInput:
        self._execution_input.assert_matches(activity)
        if self._execution_input.leaf_activity_kind is not HarnessLeafActivityKind.AGENT_LOOP:
            raise HarnessValidationError(
                "AgentLoop production activity requires an agent_loop leaf",
                code="agent_loop_graph_leaf_kind_mismatch",
            )
        if self._execution_input.required_usage is not HarnessActivityUsage.SERIAL:
            raise HarnessValidationError(
                "AgentLoop production activity is serial-only",
                code="agent_loop_graph_usage_mismatch",
            )
        return self._execution_input


class SQLiteAgentLoopActivityResultStore(HarnessGraphActivityExecutionCommitPort):
    """Durable idempotent sink for the activity result receipt.

    This stores only the outer Graph result. It has no manifest, catalog, or
    publication API; those remain Harness terminal owners.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS agent_loop_activity_results ("
            "activity_id TEXT PRIMARY KEY, activity_checksum TEXT NOT NULL, "
            "result_checksum TEXT NOT NULL, result_json TEXT NOT NULL)"
        )
        self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def commit_execution_result(
        self,
        *,
        activity: HarnessGraphActivity,
        execution_input: HarnessGraphActivityExecutionInput,
        worker_result: HarnessWorkerResult | None,
        node_output_commit: Any,
        result: HarnessGraphActivityResult,
    ) -> HarnessGraphActivityResult:
        del execution_input, worker_result, node_output_commit
        with self._lock:
            row = self._connection.execute(
                "SELECT activity_checksum, result_checksum, result_json "
                "FROM agent_loop_activity_results WHERE activity_id = ?",
                (activity.activity_id,),
            ).fetchone()
            if row is not None:
                if row[0] != activity.activity_checksum or row[1] != result.result_checksum:
                    raise HarnessValidationError(
                        "AgentLoop activity result identity conflicts",
                        code="agent_loop_activity_result_conflict",
                    )
                return _result_from_dict(json.loads(row[2]))
            self._connection.execute(
                "INSERT INTO agent_loop_activity_results "
                "(activity_id, activity_checksum, result_checksum, result_json) "
                "VALUES (?, ?, ?, ?)",
                (
                    activity.activity_id,
                    activity.activity_checksum,
                    result.result_checksum,
                    json.dumps(result.to_dict(), sort_keys=True),
                ),
            )
            self._connection.commit()
            return result

    def read(self, activity_id: str) -> HarnessGraphActivityResult | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT result_json FROM agent_loop_activity_results WHERE activity_id = ?",
                (activity_id,),
            ).fetchone()
        return None if row is None else _result_from_dict(json.loads(row[0]))


class AgentLoopGraphApplicationService:
    """Composition-owned AgentLoop Graph activity adapter.

    The caller supplies a durable Graph activity and its Harness-resolved
    execution input. This service never creates Graph state, routes nodes,
    registers waits, or writes a terminal manifest.
    """

    def __init__(
        self,
        *,
        agent_runner: AgentRunner,
        artifact_port: RunBoundArtifactPort,
        node_output_resource: HarnessNodeOutputResourcePort,
        result_committer: HarnessGraphActivityExecutionCommitPort,
        worker_ref: HarnessContractReference,
        activity_ref: HarnessContractReference,
    ) -> None:
        if not isinstance(agent_runner, AgentRunner):
            raise TypeError("agent_runner must be AgentRunner")
        if not isinstance(artifact_port, RunBoundArtifactPort):
            raise TypeError("artifact_port must implement RunBoundArtifactPort")
        if not isinstance(node_output_resource, HarnessNodeOutputResourcePort):
            raise TypeError("node_output_resource must implement node-output resource")
        if not isinstance(result_committer, HarnessGraphActivityExecutionCommitPort):
            raise TypeError("result_committer must implement result commit port")
        if not isinstance(worker_ref, HarnessContractReference) or worker_ref.contract_kind is not HarnessContractKind.WORKER:
            raise TypeError("worker_ref must be an exact worker reference")
        if not isinstance(activity_ref, HarnessContractReference) or activity_ref.contract_kind is not HarnessContractKind.ACTIVITY:
            raise TypeError("activity_ref must be an exact activity reference")
        self._runner = agent_runner
        self._artifact_port = artifact_port
        self._node_output = node_output_resource
        self._result_committer = result_committer
        self._worker_ref = worker_ref
        self._activity_ref = activity_ref

    def execute(
        self,
        *,
        activity: HarnessGraphActivity,
        execution_input: HarnessGraphActivityExecutionInput,
        agent: AgentSpec,
        attempt_id: str | None = None,
    ) -> HarnessGraphPhysicalActivityExecutionResult:
        if not isinstance(activity, HarnessGraphActivity):
            raise TypeError("activity must HarnessGraphActivity")
        if activity.worker_ref != self._worker_ref or activity.activity_ref != self._activity_ref:
            raise HarnessValidationError(
                "AgentLoop activity does not match its production binding",
                code="agent_loop_graph_activity_binding_mismatch",
            )
        if not isinstance(execution_input, HarnessGraphActivityExecutionInput):
            raise TypeError("execution_input must HarnessGraphActivityExecutionInput")
        execution_input.assert_matches(activity)
        if execution_input.leaf_activity_kind is not HarnessLeafActivityKind.AGENT_LOOP:
            raise HarnessValidationError(
                "AgentLoop production activity requires an agent_loop leaf",
                code="agent_loop_graph_leaf_kind_mismatch",
            )
        if not isinstance(agent, AgentSpec):
            raise TypeError("agent must AgentSpec")
        bundle = build_agent_loop_graph_activity_binding_bundle(
            worker_ref=self._worker_ref,
            activity_ref=self._activity_ref,
            agent_runner=self._runner,
            agent=agent,
            artifact_recorder=AgentLoopGraphArtifactRecorder(self._artifact_port),
        )
        executor = HarnessGraphPhysicalActivityExecutor(
            binding_authority=bundle.authority,
            input_resolver=_BoundInputResolver(execution_input),
            node_output_resource=self._node_output,
            result_committer=self._result_committer,
            supervisor=AttemptSupervisor(clock=lambda: utc_now().timestamp()),
        )
        return executor.execute(activity, attempt_id=attempt_id)


__all__ = [
    "AgentLoopGraphApplicationService",
    "SQLiteAgentLoopActivityResultStore",
]


def _result_from_dict(value: Mapping[str, Any]) -> HarnessGraphActivityResult:
    base_fields = {
        "schema_version", "activity_id", "node_instance_id", "attempt",
        "idempotency_key", "fencing_generation", "activity_ref", "evidence_ref",
        "payload_ref", "status", "termination_confirmed", "tenant_scope_ref",
        "identity_scope_ref", "subject_scope_ref", "result_checksum",
    }
    if not isinstance(value, Mapping):
        raise HarnessValidationError(
            "persisted AgentLoop activity result must be an object",
            code="agent_loop_activity_result_invalid",
        )
    expected = base_fields | ({"result_lineage"} if "result_lineage" in value else set())
    if set(value) != expected:
        raise HarnessValidationError(
            "persisted AgentLoop activity result fields are invalid",
            code="agent_loop_activity_result_invalid",
        )
    lineage_value = value.get("result_lineage")
    if "result_lineage" in value and not isinstance(lineage_value, Mapping):
        raise HarnessValidationError(
            "persisted AgentLoop activity result lineage must be an object",
            code="agent_loop_activity_result_invalid",
        )
    lineage = None if lineage_value is None else HarnessGraphResultLineage.from_dict(lineage_value)
    activity_ref = value["activity_ref"]
    if not isinstance(activity_ref, Mapping):
        raise HarnessValidationError(
            "persisted AgentLoop activity result reference must be an object",
            code="agent_loop_activity_result_invalid",
        )
    result = HarnessGraphActivityResult(
        schema_version=value["schema_version"],
        activity_id=value["activity_id"],
        node_instance_id=value["node_instance_id"],
        attempt=value["attempt"],
        idempotency_key=value["idempotency_key"],
        fencing_generation=value["fencing_generation"],
        activity_ref=HarnessContractReference.from_dict(activity_ref),
        evidence_ref=value["evidence_ref"],
        payload_ref=value["payload_ref"],
        status=value["status"],
        termination_confirmed=value["termination_confirmed"],
        tenant_scope_ref=value["tenant_scope_ref"],
        identity_scope_ref=value["identity_scope_ref"],
        subject_scope_ref=value["subject_scope_ref"],
        result_lineage=lineage,
    )
    if value["result_checksum"] != result.result_checksum:
        raise HarnessValidationError(
            "persisted AgentLoop activity result checksum is invalid",
            code="agent_loop_activity_result_checksum_invalid",
        )
    return result
