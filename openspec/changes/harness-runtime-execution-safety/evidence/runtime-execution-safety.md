# Harness Runtime Execution Safety Evidence

## Implemented

- `framework/execution_environment` now owns immutable `ExecutionProfile`, `ExecutionRequest`, `ExecutionReceipt`, capability admission, typed `execution_environment_unavailable`, and provider registry contracts.
- `infrastructure/execution_environment/docker.py` is the first physical provider. It rejects unsupported capability profiles, canonicalizes roots, denies network by default, bounds process count, and reports `indeterminate` when cancellation cannot be confirmed.
- `ToolExecutor` routes declared `sandboxed_process` tools through `ExecutionEnvironmentRegistry`. It does not fall back to the registered in-process callable, and raw arguments/secrets are rejected from sandbox `argv` expansion.
- `framework/harness/subagents/supervisor.py` owns child admission, leases, heartbeat, cancellation, stale reclaim, terminal receipts, duplicate-operation handling, restart recovery, and output authority boundaries.
- `framework/events/runtime/projection.py` provides a redacted runtime envelope, bounded refs/checksums, idempotent append/projection, cursor validation, replay rebuild, read-only operator status, and `RuntimeEventEmitter` adapters.
- Tool, AgentLoop, ContextCompactionRuntime, SubAgentRuntime, Worker heartbeat, and ChildAgentSupervisor can emit canonical runtime facts through the adapter.

## Verification

Focused checks completed in this worktree:

```text
.\.venv\Scripts\python.exe -m pytest tests\framework\harness\subagents\test_child_agent_supervisor.py tests\framework\execution_environment\test_execution_environment_contract.py tests\framework\tool\runtime\test_tool_execution_environment.py tests\framework\events\test_runtime_event_projection.py -q
51 passed, 2 skipped

.\.venv\Scripts\python.exe -m pytest tests\framework\harness\subagents\test_child_agent_supervisor.py tests\framework\execution_environment\test_execution_environment_contract.py tests\framework\tool\runtime\test_tool_execution_environment.py tests\framework\events\test_runtime_event_projection.py tests\interfaces\api\test_runtime_operator_status_api.py tests\interfaces\sdk\test_python_client.py tests\sdk\python\test_sdk_runs.py tests\interfaces\services\test_harness_wait_service.py tests\interfaces\services\test_harness_wait_runtime.py -q
99 passed, 2 skipped, 12 warnings

.\.venv\Scripts\python.exe -m pytest tests\framework\events\test_schema_catalog.py tests\framework\events\test_event_publisher.py tests\framework\events\test_event_projection.py -q
34 passed

.\.venv\Scripts\python.exe -m pytest tests\framework\agent\loop tests\framework\harness\context tests\framework\harness\subagents tests\framework\events\test_schema_catalog.py tests\framework\events\test_event_publisher.py tests\framework\events\test_event_projection.py -q
208 passed

.\.venv\Scripts\python.exe -m pytest tests\framework\events -q
463 passed

.\.venv\Scripts\python.exe -m pytest tests\framework\harness -q
1175 passed

.\.venv\Scripts\python.exe -m pytest tests\framework\events tests\framework\harness -q
1638 passed

.\.venv\Scripts\python.exe -m pytest tests\architecture -q
221 passed, 4 warnings

.\.venv\Scripts\python.exe -m scripts.dev sources-validate
is_valid=true, error_count=0, warning_count=0

.\.venv\Scripts\python.exe -m pytest tests\interfaces\api tests\interfaces\sdk tests\sdk\python -q
257 passed, 466 warnings

.\.venv\Scripts\python.exe -m pytest tests\interfaces\services\test_harness_wait_service.py tests\interfaces\services\test_harness_wait_runtime.py -q
35 passed

python -m scripts.dev compile
passed

.\.venv\Scripts\python.exe -m compileall -q framework infrastructure tests
passed

openspec validate harness-runtime-execution-safety --strict
Change 'harness-runtime-execution-safety' is valid

openspec validate --all --strict
537 passed, 0 failed (537 items)
```

The two skipped tests are symlink/junction adversarial cases when the host does not permit symlink creation. Docker daemon availability and production deployment rollback were not claimed by local tests.

The required smoke wrapper was run with the project `.venv` and a 10-minute
wall-clock bound. A prior bounded run completed the independent Harness and
architecture portions (`1166 passed in 53.45s` and `221 passed in 80.08s`) and
the Research/API composition suite (`941 passed, 23 deselected in 532.32s`),
but the wrapper did not return before the bound. The latest venv wrapper also
returned timeout code `124`; pytest then reported a pipe-close
`OSError: [Errno 22]` while the tool terminated the process. No full-wrapper
smoke pass is claimed.

## Qualification blockers

- `model-aware-llm-context-preflight` task 1.1 remains an external/independent work item.
- `durable-event-runtime` 9.5 remains a deployment governance, observation, and rollback qualification blocker.
- `harness-workflow-graph-runtime` 1.1 remains an upstream durable release qualification blocker.
- No governance signature, production deployment observation, provider trust activation, or rollback result is fabricated here.

## Remaining release work

Process-restart integration against a real Docker daemon, production caller scans, deployment capability matrices, and a completed full smoke wrapper remain release gates. The implementation keeps sandbox profiles fail-closed until those deployment capabilities are independently qualified; both scoped strict validations above passed.

## Implementation Reference

The path-scoped implementation commit is recorded after code review and
verification: `1332a5ed`.
