from framework.memory import (
    InMemoryMemoryStore,
    MemoryKind,
    MemoryPolicy,
    MemoryRecord,
    MemoryRuntime,
    MemoryScope,
    MemoryWriteMode,
    MemoryWriteRequest,
    DEFAULT_ADMIN_MEMORY_POLICY,
)
from framework.shared.graph_identity import GraphExecutionIdentity


def _policy(*, allow_global_write: bool = False, allow_write: bool = True) -> MemoryPolicy:
    return MemoryPolicy(
        allowed_scopes=list(MemoryScope),
        allowed_kinds=list(MemoryKind),
        allow_write=allow_write,
        allow_global_write=allow_global_write,
        require_refs=False,
    )


def _record(*, memory_id: str = "memory-1", scope: MemoryScope = MemoryScope.GRAPH) -> MemoryRecord:
    return MemoryRecord(
        memory_id=memory_id,
        content="stable memory",
        kind=MemoryKind.SEMANTIC,
        scope=scope,
    )


def test_promote_to_global_is_denied_when_global_writes_are_disabled() -> None:
    store = InMemoryMemoryStore([_record()])
    runtime = MemoryRuntime(store, policy=_policy())

    result = runtime.promote("memory-1", target_scope=MemoryScope.GLOBAL)

    assert result.written_count == 0
    assert result.errors == ["global memory writes are disabled by policy"]
    assert store.get("memory-1").scope == MemoryScope.GRAPH


def test_promote_policy_override_cannot_bypass_runtime_policy() -> None:
    store = InMemoryMemoryStore([_record()])
    runtime = MemoryRuntime(store, policy=_policy())

    result = runtime.promote(
        "memory-1",
        target_scope=MemoryScope.GLOBAL,
        policy=DEFAULT_ADMIN_MEMORY_POLICY,
    )

    assert result.written_count == 0
    assert result.errors == ["global memory writes are disabled by policy"]
    assert result.policy_decision["policy_id"] == "memory.promote"
    assert result.operation_trace is not None
    assert result.operation_trace.operation_type == "promote"
    assert store.get("memory-1").scope == MemoryScope.GRAPH


def test_promote_accepts_string_scope_and_kind_values() -> None:
    store = InMemoryMemoryStore([_record()])
    runtime = MemoryRuntime(store, policy=_policy())

    result = runtime.promote(
        "memory-1",
        target_scope="session",
        target_kind="procedural",
    )

    assert result.written_count == 1
    promoted = store.get("memory-1")
    assert promoted is not None
    assert promoted.scope is MemoryScope.SESSION
    assert promoted.kind is MemoryKind.PROCEDURAL


def test_promote_write_mode_validates_transformed_target_scope() -> None:
    store = InMemoryMemoryStore([_record()])
    runtime = MemoryRuntime(store, policy=_policy())
    identity = GraphExecutionIdentity(
        run_id="run-1",
        graph_id="graph-1",
        graph_version="v1",
        graph_ref="graph-1@v1",
        graph_checksum="sha256:" + "a" * 64,
        node_id="memory-node",
        node_instance_id="memory-instance",
        activity_id="activity-1",
        attempt=1,
    )

    result = runtime.write(
        MemoryWriteRequest(
            records=[_record()],
            mode=MemoryWriteMode.PROMOTE,
            execution_identity=identity,
        )
    )

    assert result.written_count == 0
    assert result.errors == ["global memory writes are disabled by policy"]
    assert store.get("memory-1").scope == MemoryScope.GRAPH


def test_invalidate_and_forget_apply_scope_policy() -> None:
    store = InMemoryMemoryStore([_record(scope=MemoryScope.GLOBAL)])
    runtime = MemoryRuntime(store, policy=_policy())

    invalidated = runtime.invalidate("memory-1", reason="outdated")
    forgotten = runtime.forget("memory-1")

    assert invalidated.written_count == 0
    assert invalidated.errors == ["global memory writes are disabled by policy"]
    assert invalidated.policy_decision["policy_id"] == "memory.invalidate"
    assert invalidated.operation_trace is not None
    assert invalidated.operation_trace.operation_type == "invalidate"
    assert forgotten.forgotten_count == 0
    assert forgotten.warnings == ["global memory writes are disabled by policy"]
    assert forgotten.policy_decision["allowed"] is True
    assert forgotten.operation_trace is not None
    assert forgotten.operation_trace.operation_type == "forget"
    assert forgotten.operation_trace.filtered_count == 1
    assert store.get("memory-1") is not None


def test_mutations_are_denied_when_policy_disables_writes() -> None:
    store = InMemoryMemoryStore([_record()])
    runtime = MemoryRuntime(store, policy=_policy(allow_write=False))

    promoted = runtime.promote(
        "memory-1",
        target_scope=MemoryScope.SESSION,
        policy=DEFAULT_ADMIN_MEMORY_POLICY,
    )
    invalidated = runtime.invalidate(
        "memory-1",
        reason="outdated",
        policy=DEFAULT_ADMIN_MEMORY_POLICY,
    )
    forgotten = runtime.forget("memory-1")

    assert promoted.errors == ["memory promote is disabled by policy"]
    assert promoted.policy_decision["policy_id"] == "memory.promote"
    assert promoted.operation_trace is not None
    assert promoted.operation_trace.operation_type == "promote"
    assert invalidated.errors == ["memory invalidate is disabled by policy"]
    assert invalidated.policy_decision["policy_id"] == "memory.invalidate"
    assert invalidated.operation_trace is not None
    assert invalidated.operation_trace.operation_type == "invalidate"
    assert forgotten.warnings == ["memory forget is disabled by policy"]
    assert forgotten.policy_decision["allowed"] is True
    assert forgotten.operation_trace is not None
    assert forgotten.operation_trace.policy_decision["allowed"] is True
    assert store.get("memory-1") is not None
