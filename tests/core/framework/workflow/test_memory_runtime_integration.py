import json
from pathlib import Path

from core.framework.artifacts import ArtifactManager
from core.framework.memory import InMemoryMemoryStore, MemoryRecord, MemoryRuntime
from core.framework.specs import EdgeSpec, StepSpec, StepStatus, StepType, WorkflowSpec, WorkflowStatus
from core.framework.workflow import (
    DataBuffer,
    FunctionStepRegistry,
    MemoryConsolidateStepRunner,
    MemoryRecallStepRunner,
    MemoryWriteStepRunner,
    WorkflowExecutor,
    build_default_step_runner_registry,
    build_runner_manifest,
)


def test_memory_recall_step_reads_runtime_and_writes_buffer(tmp_path) -> None:
    runtime = MemoryRuntime(
        InMemoryMemoryStore(
            [
                MemoryRecord(
                    memory_id="mem-1",
                    scope="workflow",
                    kind="semantic",
                content="workflow memory context is available",
                summary="workflow memory context",
                refs={"run_id": "run-1"},
            )
            ]
        )
    )
    runner = MemoryRecallStepRunner(runtime)
    runner.configure_run_context(artifact_manager=ArtifactManager(tmp_path), run_id="run-1")
    data_buffer = DataBuffer({"query": "workflow memory"})
    scoped = data_buffer.scope(
        read_keys=["query"],
        write_keys=["memory_recall_result", "memory_context", "memory_records"],
        step_id="recall",
    )
    step = StepSpec(
        step_id="recall",
        implementation="memory.recall",
        step_type=StepType.MEMORY_RECALL,
        read_keys=["query"],
        write_keys=["memory_recall_result", "memory_context", "memory_records"],
        required_output_keys=["memory_recall_result", "memory_context", "memory_records"],
        metadata={"query_key": "query"},
    )

    outcome = runner.run(step, scoped)

    assert outcome.status == StepStatus.SUCCEEDED
    assert outcome.lineage[0]["event_type"] == "memory_recall"
    assert outcome.metrics["memory_operation"]["operation"] == "recall"
    assert data_buffer.read("memory_recall_result")["result_count"] == 1
    assert "workflow memory context" in data_buffer.read("memory_context")["content"]
    assert data_buffer.read("memory_records")[0]["memory_id"] == "mem-1"


def test_memory_write_step_writes_runtime_records_with_run_id_refs(tmp_path) -> None:
    store = InMemoryMemoryStore()
    runtime = MemoryRuntime(store)
    runner = MemoryWriteStepRunner(runtime)
    runner.configure_run_context(artifact_manager=ArtifactManager(tmp_path), run_id="run-1")
    data_buffer = DataBuffer()
    scoped = data_buffer.scope(
        read_keys=[],
        write_keys=["memory_write_result"],
        step_id="write",
    )
    step = StepSpec(
        step_id="write",
        implementation="memory.write",
        step_type=StepType.MEMORY_WRITE,
        write_keys=["memory_write_result"],
        required_output_keys=["memory_write_result"],
        metadata={
            "approval_id": "appr-memory-write",
            "records": [
                {
                    "memory_id": "mem-1",
                    "scope": "workflow",
                    "kind": "semantic",
                    "content": "workflow memory written by the step",
                }
            ],
        },
    )

    outcome = runner.run(step, scoped)

    assert outcome.status == StepStatus.SUCCEEDED
    assert outcome.lineage[0]["event_type"] == "memory_write"
    assert outcome.metrics["memory_operation"]["operation"] == "write"
    assert data_buffer.read("memory_write_result")["written_count"] == 1
    assert store.get("mem-1").refs["run_id"] == "run-1"


def test_memory_consolidate_step_consolidates_runtime_records_with_run_id_refs(tmp_path) -> None:
    store = InMemoryMemoryStore(
        [
            MemoryRecord(
                memory_id="mem-source-1",
                scope="workflow",
                kind="semantic",
                content="first workflow memory source",
                refs={"run_id": "source-run"},
            ),
            MemoryRecord(
                memory_id="mem-source-2",
                scope="workflow",
                kind="semantic",
                content="second workflow memory source",
                refs={"run_id": "source-run"},
            ),
        ]
    )
    runtime = MemoryRuntime(store)
    runner = MemoryConsolidateStepRunner(runtime)
    runner.configure_run_context(artifact_manager=ArtifactManager(tmp_path), run_id="run-1")
    data_buffer = DataBuffer()
    scoped = data_buffer.scope(
        read_keys=[],
        write_keys=["memory_consolidate_result"],
        step_id="consolidate",
    )
    step = StepSpec(
        step_id="consolidate",
        implementation="memory.consolidate",
        step_type=StepType.MEMORY_CONSOLIDATE,
        write_keys=["memory_consolidate_result"],
        required_output_keys=["memory_consolidate_result"],
        metadata={
            "approval_id": "appr-memory-consolidate",
            "memory_ids": ["mem-source-1", "mem-source-2"],
            "reason": "stable workflow summary",
        },
    )

    outcome = runner.run(step, scoped)

    assert outcome.status == StepStatus.SUCCEEDED
    assert outcome.lineage[0]["event_type"] == "memory_consolidate"
    assert outcome.metrics["memory_operation"]["operation"] == "consolidate"
    payload = data_buffer.read("memory_consolidate_result")
    assert payload["consolidated_count"] == 1
    assert payload["source_memory_ids"] == ["mem-source-1", "mem-source-2"]
    consolidated = runtime.get(payload["memory_ids"][0])
    assert consolidated is not None
    assert consolidated.refs["run_id"] == "run-1"
    assert consolidated.refs["source_memory_ids"] == ["mem-source-1", "mem-source-2"]


def test_workflow_executor_write_then_recall_outputs_context_block(tmp_path) -> None:
    runtime = MemoryRuntime(InMemoryMemoryStore())
    registry = build_default_step_runner_registry(
        FunctionStepRegistry(),
        memory_runtime=runtime,
    )
    workflow = WorkflowSpec(
        workflow_id="memory-runtime-workflow",
        name="Memory Runtime Workflow",
        version="1.0",
        start_step_id="write_memory",
        terminal_step_ids=["recall_memory"],
        steps=[
            StepSpec(
                step_id="write_memory",
                implementation="memory.write",
                step_type=StepType.MEMORY_WRITE,
                write_keys=["memory_write_result"],
                required_output_keys=["memory_write_result"],
                metadata={
                    "approval_id": "appr-memory-write",
                    "records": [
                        {
                            "memory_id": "mem-workflow",
                            "scope": "workflow",
                            "kind": "semantic",
                            "content": "workflow memory makes the context block visible",
                        }
                    ],
                },
            ),
            StepSpec(
                step_id="recall_memory",
                implementation="memory.recall",
                step_type=StepType.MEMORY_RECALL,
                write_keys=["memory_recall_result", "memory_context", "memory_records"],
                required_output_keys=["memory_recall_result", "memory_context", "memory_records"],
                metadata={"query": "workflow memory"},
            ),
        ],
        edges=[EdgeSpec(edge_id="write-to-recall", source_step_id="write_memory", target_step_id="recall_memory")],
    )
    executor = WorkflowExecutor(
        function_step_runner=None,
        artifact_manager=ArtifactManager(tmp_path),
        step_runner_registry=registry,
    )

    result = executor.execute(workflow, {}, profile="test", run_id="run-1")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["memory_recall_result"]["result_count"] == 1
    assert "context block visible" in result.output["memory_context"]["content"]
    assert runtime.get("mem-workflow").refs["run_id"] == "run-1"
    assert result.step_results["write_memory"].lineage[0]["event_type"] == "memory_write"
    assert result.step_results["recall_memory"].lineage[0]["event_type"] == "memory_recall"
    assert result.manifest["memory_operations"]["operation_count"] == 2
    assert result.manifest["memory_operations"]["write_count"] == 1
    assert result.manifest["memory_operations"]["recall_count"] == 1
    assert result.manifest["memory_operations"]["written_memory_ids"] == ["mem-workflow"]
    assert result.manifest["metrics"]["memory_operations"]["total_written_records"] == 1
    assert result.events_path is not None
    events = [
        json.loads(line)
        for line in Path(result.events_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    event_types = {event["event_type"] for event in events}
    assert "memory_write" in event_types
    assert "memory_recall" in event_types


def test_default_registry_and_runner_manifest_expose_memory_dependency_status() -> None:
    missing_registry = build_default_step_runner_registry(FunctionStepRegistry())
    missing_descriptors = {item.runner_id: item for item in missing_registry.describe()}

    assert missing_descriptors["builtin.memory_recall"].available is False
    assert missing_descriptors["builtin.memory_recall"].missing_dependencies == ["memory_runtime"]
    assert missing_descriptors["builtin.memory_write"].available is False
    assert missing_descriptors["builtin.memory_write"].missing_dependencies == ["memory_runtime"]
    assert missing_descriptors["builtin.memory_consolidate"].available is False
    assert missing_descriptors["builtin.memory_consolidate"].missing_dependencies == ["memory_runtime"]

    runtime = MemoryRuntime(InMemoryMemoryStore())
    registry = build_default_step_runner_registry(
        FunctionStepRegistry(),
        memory_runtime=runtime,
    )
    descriptors = {item.runner_id: item for item in registry.describe()}

    assert descriptors["builtin.memory_recall"].available is True
    assert descriptors["builtin.memory_recall"].missing_dependencies == []
    assert descriptors["builtin.memory_write"].available is True
    assert descriptors["builtin.memory_write"].missing_dependencies == []
    assert descriptors["builtin.memory_consolidate"].available is True
    assert descriptors["builtin.memory_consolidate"].missing_dependencies == []

    workflow = WorkflowSpec(
        workflow_id="memory-manifest",
        name="Memory Manifest",
        version="1.0",
        start_step_id="recall_memory",
        steps=[
            StepSpec(
                step_id="recall_memory",
                implementation="memory.recall",
                step_type=StepType.MEMORY_RECALL,
                write_keys=["memory_recall_result", "memory_context", "memory_records"],
                metadata={"query": "workflow memory"},
            )
        ],
    )
    manifest = build_runner_manifest(workflow, registry)

    assert manifest.runners[0].runner_id == "builtin.memory_recall"
    assert manifest.runners[0].required_dependencies == ["memory_runtime"]
    assert manifest.runners[0].missing_dependencies == []
    assert manifest.runners[0].available is True


def test_workflow_executor_write_consolidate_recall_tracks_memory_operations(tmp_path) -> None:
    runtime = MemoryRuntime(InMemoryMemoryStore())
    registry = build_default_step_runner_registry(
        FunctionStepRegistry(),
        memory_runtime=runtime,
    )
    workflow = WorkflowSpec(
        workflow_id="memory-consolidate-workflow",
        name="Memory Consolidate Workflow",
        version="1.0",
        start_step_id="write_one",
        terminal_step_ids=["recall_consolidated"],
        steps=[
            StepSpec(
                step_id="write_one",
                implementation="memory.write",
                step_type=StepType.MEMORY_WRITE,
                write_keys=["write_one_result"],
                required_output_keys=["write_one_result"],
                metadata={
                    "approval_id": "appr-memory-write-1",
                    "result_key": "write_one_result",
                    "records": [
                        {
                            "memory_id": "mem-source-1",
                            "scope": "workflow",
                            "kind": "semantic",
                            "content": "workflow memory source one",
                        }
                    ],
                },
            ),
            StepSpec(
                step_id="write_two",
                implementation="memory.write",
                step_type=StepType.MEMORY_WRITE,
                write_keys=["write_two_result"],
                required_output_keys=["write_two_result"],
                metadata={
                    "approval_id": "appr-memory-write-2",
                    "result_key": "write_two_result",
                    "records": [
                        {
                            "memory_id": "mem-source-2",
                            "scope": "workflow",
                            "kind": "semantic",
                            "content": "workflow memory source two",
                        }
                    ],
                },
            ),
            StepSpec(
                step_id="consolidate_memory",
                implementation="memory.consolidate",
                step_type=StepType.MEMORY_CONSOLIDATE,
                write_keys=["memory_consolidate_result"],
                required_output_keys=["memory_consolidate_result"],
                metadata={
                    "approval_id": "appr-memory-consolidate",
                    "memory_ids": ["mem-source-1", "mem-source-2"],
                    "reason": "stable workflow summary",
                },
            ),
            StepSpec(
                step_id="recall_consolidated",
                implementation="memory.recall",
                step_type=StepType.MEMORY_RECALL,
                write_keys=["memory_recall_result", "memory_context", "memory_records"],
                required_output_keys=["memory_recall_result", "memory_context", "memory_records"],
                metadata={"query": "stable workflow summary"},
            ),
        ],
        edges=[
            EdgeSpec(edge_id="write-one-to-two", source_step_id="write_one", target_step_id="write_two"),
            EdgeSpec(edge_id="write-two-to-consolidate", source_step_id="write_two", target_step_id="consolidate_memory"),
            EdgeSpec(edge_id="consolidate-to-recall", source_step_id="consolidate_memory", target_step_id="recall_consolidated"),
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=None,
        artifact_manager=ArtifactManager(tmp_path),
        step_runner_registry=registry,
    )

    result = executor.execute(workflow, {}, profile="test", run_id="run-1")

    assert result.status == WorkflowStatus.SUCCEEDED
    consolidate_payload = result.output["memory_consolidate_result"]
    assert consolidate_payload["consolidated_count"] == 1
    consolidated_id = consolidate_payload["memory_ids"][0]
    assert runtime.get(consolidated_id).refs["run_id"] == "run-1"
    assert result.manifest["memory_operations"]["operation_count"] == 4
    assert result.manifest["memory_operations"]["write_count"] == 2
    assert result.manifest["memory_operations"]["consolidate_count"] == 1
    assert result.manifest["memory_operations"]["recall_count"] == 1
    assert result.manifest["memory_operations"]["consolidated_memory_ids"] == [consolidated_id]
    assert result.manifest["metrics"]["memory_operations"]["total_consolidated_records"] == 1
    events = [
        json.loads(line)
        for line in Path(result.events_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert "memory_consolidate" in {event["event_type"] for event in events}
