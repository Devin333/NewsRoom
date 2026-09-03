from __future__ import annotations

import base64
from dataclasses import replace
from datetime import timedelta

import pytest

from framework.events.canonical import checksum_for
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.graph_application import (
    HarnessGraphControlPlaneRuntime,
)
from framework.harness.runtime import (
    GraphArtifactResultError,
    GraphArtifactResultErrorCode,
    HarnessGraphResultRuntime,
    PersistenceMode,
)
from framework.harness.runtime.tool_result_adapter import (
    TOOL_RESPONSE_DOCUMENT_SCHEMA,
    TOOL_SIDE_EFFECT_EVIDENCE_SCHEMA,
    HarnessBoundToolSideEffectReceipt,
    HarnessToolResultAdapter,
    build_harness_tool_activity_runtime,
    verify_harness_tool_side_effect_evidence,
)
from framework.shared.json import stable_json_dumps
from framework.tool import (
    MCPServerConfig,
    MCPToolAdapter,
    ToolCall,
    ToolDefinition,
    ToolExecutor,
    ToolPolicy,
    ToolRuntimeError,
)
from framework.tool.registry import ToolRegistry
from tests.framework.harness.runtime.test_graph_result_runtime import (
    NOW,
    TENANT_ID,
    TENANT_SCOPE_REF,
    FailResultProjectionPort,
    _dispatched,
)
from tests.framework.harness.runtime.test_materializer import (
    DEPENDENCY,
    RecordingArtifactPort,
    RecordingAttempts,
    RecordingCache,
    RecordingCatalog,
    RecordingQuota,
    _materializer,
)


def _runtime(
    fixture,
    definition: ToolDefinition,
    executor_fn,
    *,
    artifact=None,
    attempts=None,
    cache=None,
    catalog=None,
    execution_environment=None,
):
    registry = ToolRegistry()
    registry.register(definition, executor_fn)
    artifact = artifact or RecordingArtifactPort()
    attempts = attempts or RecordingAttempts()
    cache = cache or RecordingCache()
    catalog = catalog or RecordingCatalog()
    materializer = _materializer(
        artifact=artifact,
        attempts=attempts,
        cache=cache,
        catalog=catalog,
        quota=RecordingQuota(),
    )
    graph_runtime = HarnessGraphControlPlaneRuntime(fixture.port)
    adapter = HarnessToolResultAdapter(
        materializer=materializer,
        graph_result_runtime=HarnessGraphResultRuntime(graph_runtime),
        clock=lambda: NOW,
    )
    runtime = build_harness_tool_activity_runtime(
        registry=registry,
        materializer=materializer,
        graph_runtime=graph_runtime,
        execution_environment=execution_environment,
    )
    return (
        runtime,
        adapter,
        materializer,
        artifact,
        attempts,
        cache,
        catalog,
        registry,
    )


def test_harness_tool_runtime_binds_execution_environment() -> None:
    fixture = _dispatched("run-tool-environment")
    definition = ToolDefinition(name="sample.echo")
    environment = object()
    runtime, *_ = _runtime(
        fixture,
        definition,
        lambda _args: {"ok": True},
        execution_environment=environment,
    )

    assert runtime._executor._execution_environment is environment


def _execute(runtime, fixture, definition, *, call_id="call-1", policy=None):
    return runtime.execute_and_accept(
        activity=fixture.activity,
        call=ToolCall(tool_name=definition.name, call_id=call_id),
        policy=policy
        or ToolPolicy(
            allowed_tools=[definition.name],
            require_explicit_allowlist=True,
            require_approval_for_side_effects=False,
        ),
        graph=fixture.graph,
        tenant_id=TENANT_ID,
        tenant_scope_ref=TENANT_SCOPE_REF,
        run_spec_checksum=fixture.run_spec_checksum,
        occurred_at=NOW + timedelta(minutes=1),
    )


def _stored_candidate(artifact, result):
    ref = result.materialization.envelope.materialized_refs[0].ref
    return artifact.read_artifact(ref)["payload"]


def _lineage(result, fixture):
    node = next(
        item
        for item in result.graph_state.node_instances
        if item.instance_id == fixture.activity.node_instance_id
    )
    return node.output_refs["activity_result_lineage"]


def test_large_paginated_tool_result_materializes_raw_body_and_projects_controls() -> None:
    fixture = _dispatched("run-tool-large")
    definition = ToolDefinition(
        name="sample.search",
        output_schema={
            "type": "object",
            "properties": {
                "items": {"type": "array"},
                "next_cursor": {"type": "string"},
                "has_more": {"type": "boolean"},
            },
            "required": ["items", "next_cursor", "has_more"],
        },
        max_result_bytes=200_000,
        result_persistence={
            "control_fields": ["next_cursor", "has_more"],
        },
    )
    response = {
        "status": "ok",
        "items": [{"id": index, "body": "x" * 80} for index in range(600)],
        "next_cursor": "cursor-2",
        "has_more": True,
    }
    runtime, _adapter, _materializer_value, artifact, _attempts, _cache, catalog, _registry = (
        _runtime(fixture, definition, lambda _args: response)
    )

    result = _execute(runtime, fixture, definition)
    envelope = result.materialization.envelope
    lineage = _lineage(result, fixture)
    stored = _stored_candidate(artifact, result)

    assert envelope.persistence_decision.mode is PersistenceMode.ARTIFACT
    assert stored["encoding"] == "json"
    assert stored["value"]["response_schema"] == TOOL_RESPONSE_DOCUMENT_SCHEMA
    assert stored["value"]["tool_id"] == definition.tool_id
    assert stored["value"]["response"] == response
    assert stored["value"]["response_checksum"] == (
        lineage["inline_projection"]["response_checksum"]
    )
    assert lineage["inline_projection"]["next_cursor"] == "cursor-2"
    assert lineage["inline_projection"]["has_more"] is True
    assert "items" not in lineage["inline_projection"]
    assert len(lineage["artifact_refs"]) == 1
    assert len(catalog.requests) == 1
    assert "\"items\"" not in stable_json_dumps(result.graph_state.to_dict())


def test_binary_tool_result_round_trips_through_common_artifact_path() -> None:
    fixture = _dispatched("run-tool-binary")
    payload = b"\x00\xffPDF\r\n" + bytes(range(128))
    definition = ToolDefinition(
        name="sample.pdf",
        output_schema=None,
        result_persistence={
            "media_type": "application/pdf",
            "sensitivity": "restricted",
            "required_for_replay": True,
        },
    )
    runtime, _adapter, _materializer_value, artifact, _attempts, _cache, _catalog, _registry = (
        _runtime(fixture, definition, lambda _args: payload)
    )

    result = _execute(runtime, fixture, definition)
    stored = _stored_candidate(artifact, result)

    assert result.materialization.envelope.persistence_decision.mode is PersistenceMode.ARTIFACT
    assert stored["media_type"] == "application/pdf"
    assert stored["encoding"] == "base64"
    assert base64.b64decode(stored["value"], validate=True) == payload
    assert _lineage(result, fixture)["inline_projection"]["response_checksum"] == (
        result.materialization.envelope.candidate_checksum
    )


def test_side_effect_receipt_is_required_evidence_and_queryable_from_lineage() -> None:
    fixture = _dispatched("run-tool-side-effect")
    definition = ToolDefinition(
        name="sample.write",
        side_effect="writes_external_state",
        metadata={"idempotent": True, "reconciliation_supported": True},
    )
    runtime, _adapter, _materializer_value, artifact, attempts, _cache, catalog, _registry = (
        _runtime(
            fixture,
            definition,
            lambda _args: {"external_id": "record-1"},
        )
    )

    result = _execute(runtime, fixture, definition)
    envelope = result.materialization.envelope
    lineage = _lineage(result, fixture)
    stored = _stored_candidate(artifact, result)["value"]
    receipt_projection = lineage["inline_projection"]["side_effect_receipt"]

    assert envelope.persistence_decision.mode is PersistenceMode.ARTIFACT
    assert envelope.persistence_decision.required is True
    assert envelope.materialized_refs[0].artifact_class.value == "evidence"
    assert envelope.materialized_refs[0].required_for_replay is True
    assert stored["evidence_schema"] == TOOL_SIDE_EFFECT_EVIDENCE_SCHEMA
    receipt = HarnessBoundToolSideEffectReceipt.from_dict(stored["receipt"])
    verified = verify_harness_tool_side_effect_evidence(
        stored,
        expected_binding=envelope.binding,
    )
    assert receipt.binding == envelope.binding
    assert receipt.bound_receipt_checksum == receipt_projection["bound_receipt_checksum"]
    assert receipt.tool_receipt.receipt_checksum == receipt_projection["tool_receipt_checksum"]
    assert receipt.graph_binding_checksum == receipt_projection["graph_binding_checksum"]
    assert receipt.tool_receipt.response_checksum == stored["response_checksum"]
    assert verified.response == {"external_id": "record-1"}
    assert catalog.requests[0].record == envelope.materialized_refs[0]
    assert attempts.get(envelope.binding) == envelope

    tampered = stored["receipt"].copy()
    tampered["graph_binding_checksum"] = checksum_for("wrong-binding")
    with pytest.raises(ToolRuntimeError, match="checksum is invalid"):
        HarnessBoundToolSideEffectReceipt.from_dict(tampered)

    tampered_evidence = dict(stored)
    tampered_evidence["response"] = {"external_id": "changed"}
    with pytest.raises(ToolRuntimeError, match="integrity is invalid"):
        verify_harness_tool_side_effect_evidence(
            tampered_evidence,
            expected_binding=envelope.binding,
        )


def test_cache_eligible_tool_still_runs_authorization_and_gate_first() -> None:
    fixture = _dispatched("run-tool-cache")
    calls = 0

    def execute(_args):
        nonlocal calls
        calls += 1
        return {"value": "deterministic"}

    definition = ToolDefinition(
        name="sample.cached",
        result_persistence={
            "reusable": True,
            "dependency_digest": DEPENDENCY,
        },
    )
    runtime, _adapter, _materializer_value, artifact, attempts, cache, _catalog, _registry = (
        _runtime(fixture, definition, execute)
    )
    denied = ToolPolicy(allowed_tools=[], require_explicit_allowlist=True)

    with pytest.raises(ToolRuntimeError, match="cannot be materialized"):
        _execute(runtime, fixture, definition, policy=denied)

    assert calls == 0
    assert cache.write_count == 0
    assert attempts.put_count == 0
    assert artifact.write_count == 0

    accepted = _execute(runtime, fixture, definition)

    assert calls == 1
    assert accepted.observation is not None
    checks = {
        item["check_id"]: item["passed"]
        for item in accepted.observation.result.policy_trace.checks
    }
    assert checks["tool.permission"] is True
    assert checks["tool.approval"] is True
    assert accepted.observation.result.gate_result is not None
    assert accepted.materialization.envelope.persistence_decision.mode is PersistenceMode.CACHE
    assert cache.write_count == 1


def test_cross_run_binding_is_rejected_before_any_materialization_write() -> None:
    fixture = _dispatched("run-tool-scope")
    definition = ToolDefinition(
        name="sample.scope",
        result_persistence={"required_for_replay": True},
    )
    runtime, adapter, materializer, artifact, attempts, cache, catalog, registry = _runtime(
        fixture,
        definition,
        lambda _args: {"ok": True},
    )
    binding = adapter.binding_for_activity(
        activity=fixture.activity,
        graph=fixture.graph,
        tenant_id=TENANT_ID,
        tenant_scope_ref=TENANT_SCOPE_REF,
        run_spec_checksum=fixture.run_spec_checksum,
    )
    observation = ToolExecutor(
        registry,
        defer_result_persistence=True,
    ).execute(
        ToolCall(tool_name=definition.name, call_id="call-scope"),
        ToolPolicy(allowed_tools=[definition.name]),
    )
    wrong = replace(binding, run_id="run-other")

    with pytest.raises(HarnessValidationError) as rejected:
        adapter.materialize_and_accept(
            observation,
            registry.get(definition.name).definition,
            binding=wrong,
            activity=fixture.activity,
            graph=fixture.graph,
            run_spec_checksum=fixture.run_spec_checksum,
            occurred_at=NOW + timedelta(minutes=1),
        )

    assert rejected.value.code == "graph_result_lineage_scope_mismatch"
    assert artifact.write_count == 0
    assert attempts.put_count == 0
    assert cache.write_count == 0
    assert catalog.requests == []


def test_retry_reuses_materialized_object_and_conflict_does_not_overwrite() -> None:
    fixture = _dispatched("run-tool-dedup")
    definition = ToolDefinition(
        name="sample.evidence",
        result_persistence={"required_for_replay": True},
    )
    runtime, adapter, _materializer_value, artifact, attempts, _cache, _catalog, _registry = (
        _runtime(fixture, definition, lambda _args: {"value": "first"})
    )
    first = _execute(runtime, fixture, definition)
    assert first.observation is not None

    duplicate = adapter.materialize_and_accept(
        first.observation,
        definition,
        binding=first.materialization.envelope.binding,
        activity=fixture.activity,
        graph=fixture.graph,
        run_spec_checksum=fixture.run_spec_checksum,
        occurred_at=NOW + timedelta(minutes=2),
    )

    assert duplicate.materialization.envelope == first.materialization.envelope
    assert artifact.write_count == 1
    assert attempts.put_count == 1

    other_registry = ToolRegistry()
    other_registry.register(definition, lambda _args: {"value": "different"})
    conflicting_observation = ToolExecutor(
        other_registry,
        defer_result_persistence=True,
    ).execute(
        ToolCall(tool_name=definition.name, call_id="call-1"),
        ToolPolicy(allowed_tools=[definition.name]),
    )
    with pytest.raises(GraphArtifactResultError) as conflict:
        adapter.materialize_and_accept(
            conflicting_observation,
            definition,
            binding=first.materialization.envelope.binding,
            activity=fixture.activity,
            graph=fixture.graph,
            run_spec_checksum=fixture.run_spec_checksum,
            occurred_at=NOW + timedelta(minutes=3),
        )

    assert conflict.value.error_code is GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT
    assert artifact.write_count == 1
    assert attempts.get(first.materialization.envelope.binding) == first.materialization.envelope


def test_restart_after_materialization_recovers_without_tool_reexecution() -> None:
    port = FailResultProjectionPort()
    fixture = _dispatched("run-tool-restart", port=port)
    calls = 0

    def execute(_args):
        nonlocal calls
        calls += 1
        return {"value": "durable"}

    definition = ToolDefinition(
        name="sample.restart",
        result_persistence={"required_for_replay": True},
    )
    artifact = RecordingArtifactPort()
    attempts = RecordingAttempts()
    cache = RecordingCache()
    catalog = RecordingCatalog()
    (
        runtime,
        _adapter,
        _materializer_value,
        _artifact,
        _attempts,
        _cache,
        _catalog,
        registry,
    ) = _runtime(
        fixture,
        definition,
        execute,
        artifact=artifact,
        attempts=attempts,
        cache=cache,
        catalog=catalog,
    )
    port.fail_result_projection = True

    with pytest.raises(RuntimeError, match="result projection unavailable"):
        _execute(runtime, fixture, definition)

    assert calls == 1
    assert artifact.write_count == 1
    assert attempts.put_count == 1
    interrupted = port.recover_graph(fixture.activity.run_id)
    assert len(interrupted.pending_activity_results) == 1

    restarted_materializer = _materializer(
        artifact=artifact,
        attempts=attempts,
        cache=cache,
        catalog=catalog,
        quota=RecordingQuota(),
    )
    restarted = build_harness_tool_activity_runtime(
        registry=registry,
        materializer=restarted_materializer,
        graph_runtime=HarnessGraphControlPlaneRuntime(port),
    )
    recovered = restarted.recover_and_accept(
        activity=fixture.activity,
        graph=fixture.graph,
        tenant_id=TENANT_ID,
        tenant_scope_ref=TENANT_SCOPE_REF,
        run_spec_checksum=fixture.run_spec_checksum,
        occurred_at=NOW + timedelta(minutes=2),
    )

    assert recovered.recovered is True
    assert recovered.observation is None
    assert calls == 1
    assert artifact.write_count == 1
    assert attempts.put_count == 1
    assert port.recover_graph(fixture.activity.run_id).pending_activity_results == ()


def test_restart_after_mcp_materialization_does_not_recall_remote_server() -> None:
    class RemoteClient:
        def __init__(self) -> None:
            self.calls = 0

        @staticmethod
        def list_tools(_server):
            return [
                {
                    "name": "lookup",
                    "side_effect": "read_only",
                    "is_dangerous": False,
                    "requires_approval": False,
                    "inputSchema": {"type": "object", "properties": {}},
                    "resultPersistence": {"required_for_replay": True},
                }
            ]

        def call_tool(self, _server, remote_tool_name, arguments):
            assert remote_tool_name == "lookup"
            assert arguments == {}
            self.calls += 1
            return {"value": "durable-mcp-result"}

    port = FailResultProjectionPort()
    fixture = _dispatched("run-mcp-restart", port=port)
    client = RemoteClient()
    registry = ToolRegistry()
    definition = MCPToolAdapter(client).register_tools(
        registry,
        MCPServerConfig(
            server_id="remote-search",
            name="Remote Search",
            transport="in_memory",
        ),
    )[0]
    artifact = RecordingArtifactPort()
    attempts = RecordingAttempts()
    cache = RecordingCache()
    catalog = RecordingCatalog()
    materializer = _materializer(
        artifact=artifact,
        attempts=attempts,
        cache=cache,
        catalog=catalog,
        quota=RecordingQuota(),
    )
    runtime = build_harness_tool_activity_runtime(
        registry=registry,
        materializer=materializer,
        graph_runtime=HarnessGraphControlPlaneRuntime(port),
    )
    policy = ToolPolicy(
        allowed_tools=[definition.name],
        allow_mcp_tools=True,
        require_explicit_allowlist=True,
        require_approval_for_side_effects=False,
    )
    port.fail_result_projection = True

    with pytest.raises(RuntimeError, match="result projection unavailable"):
        _execute(runtime, fixture, definition, policy=policy)

    assert client.calls == 1
    assert artifact.write_count == 1
    assert attempts.put_count == 1

    restarted = build_harness_tool_activity_runtime(
        registry=registry,
        materializer=_materializer(
            artifact=artifact,
            attempts=attempts,
            cache=cache,
            catalog=catalog,
            quota=RecordingQuota(),
        ),
        graph_runtime=HarnessGraphControlPlaneRuntime(port),
    )
    recovered = restarted.recover_and_accept(
        activity=fixture.activity,
        graph=fixture.graph,
        tenant_id=TENANT_ID,
        tenant_scope_ref=TENANT_SCOPE_REF,
        run_spec_checksum=fixture.run_spec_checksum,
        occurred_at=NOW + timedelta(minutes=2),
    )

    assert recovered.recovered is True
    assert client.calls == 1
    assert artifact.write_count == 1
    assert attempts.put_count == 1
