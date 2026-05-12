import time
from threading import Lock

from core.framework.tools import (
    ToolBatchExecutor,
    ToolCall,
    ToolDefinition,
    ToolPolicy,
    ToolRegistry,
    ToolStatus,
)


def test_tool_batch_executor_parallelizes_safe_read_only_tools() -> None:
    active = {"count": 0, "max": 0}
    lock = Lock()

    def slow_read(args: dict) -> dict:
        with lock:
            active["count"] += 1
            active["max"] = max(active["max"], active["count"])
        time.sleep(0.2)
        with lock:
            active["count"] -= 1
        return {"id": args["id"]}

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="memory.slow_read",
            input_schema={"required": ["id"]},
            concurrency_safe=True,
        ),
        slow_read,
    )
    executor = ToolBatchExecutor(registry, max_workers=2)

    started_at = time.perf_counter()
    observations = executor.execute_batch(
        [
            ToolCall(tool_name="memory.slow_read", arguments={"id": "a"}),
            ToolCall(tool_name="memory.slow_read", arguments={"id": "b"}),
        ],
        ToolPolicy(allowed_tools=["memory.slow_read"], timeout_seconds_default=1.0),
    )
    elapsed = time.perf_counter() - started_at

    assert [observation.status for observation in observations] == [
        ToolStatus.SUCCEEDED,
        ToolStatus.SUCCEEDED,
    ]
    assert [observation.result.output["id"] for observation in observations] == ["a", "b"]
    assert active["max"] == 2
    assert elapsed < 0.35


def test_tool_batch_executor_serializes_side_effecting_tools() -> None:
    active = {"count": 0, "max": 0}
    lock = Lock()

    def local_write(args: dict) -> dict:
        with lock:
            active["count"] += 1
            active["max"] = max(active["max"], active["count"])
        time.sleep(0.05)
        with lock:
            active["count"] -= 1
        return {"id": args["id"]}

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="local.write",
            input_schema={"required": ["id"]},
            side_effect="writes_local_state",
            concurrency_safe=True,
        ),
        local_write,
    )
    executor = ToolBatchExecutor(registry, max_workers=2)

    observations = executor.execute_batch(
        [
            ToolCall(tool_name="local.write", arguments={"id": "a"}),
            ToolCall(tool_name="local.write", arguments={"id": "b"}),
        ],
        ToolPolicy(
            allowed_tools=["local.write"],
            require_approval_for_side_effects=False,
            timeout_seconds_default=1.0,
        ),
    )

    assert [observation.status for observation in observations] == [
        ToolStatus.SUCCEEDED,
        ToolStatus.SUCCEEDED,
    ]
    assert [observation.result.output["id"] for observation in observations] == ["a", "b"]
    assert active["max"] == 1


def test_tool_batch_executor_blocks_batches_over_iteration_budget() -> None:
    calls = {"count": 0}
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(name="memory.search", input_schema={"required": ["query"]}),
        lambda args: calls.__setitem__("count", calls["count"] + 1),
    )
    executor = ToolBatchExecutor(registry)

    observations = executor.execute_batch(
        [
            ToolCall(tool_name="memory.search", arguments={"query": "a"}),
            ToolCall(tool_name="memory.search", arguments={"query": "b"}),
        ],
        ToolPolicy(allowed_tools=["memory.search"], max_tool_calls_per_iteration=1),
    )

    assert [observation.status for observation in observations] == [
        ToolStatus.BLOCKED,
        ToolStatus.BLOCKED,
    ]
    assert calls["count"] == 0
    assert "max_tool_calls_per_iteration" in (observations[0].result.error_message or "")
