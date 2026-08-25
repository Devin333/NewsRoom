## Why

NewsRoom 已经具备 Graph-only 控制、确定性 gate、Graph identity、durable replay 和 side-effect authority，但工具授权目前主要停留在调用前的 policy 判断，子 Agent 主要是同步 worker 调用，运行态事件也分散在 tool、approval、AgentLoop、context 和 worker 记录中。要缩短与 Codex Harness 的实际运行时差距，需要把“允许做什么”落实为“只能在什么执行环境中做”，并让长任务、取消、恢复和观测拥有统一的 Harness 边界。

本 change 不重做 NewsRoom 的业务 Graph，也不把 routing、quality、memory 或 publication 交给 LLM。它为现有 Graph control plane 增加安全执行环境、子 Agent 生命周期监管和运行时事件投影，同时完成能够在仓库内完成的验证收口。

## What Changes

- 增加由 Harness 掌权的 `ExecutionEnvironmentPort`，将 tool execution 绑定到文件系统、网络、环境变量、子进程和取消限制。
- 对不具备所需物理限制能力的 deployment fail closed；policy 允许不再等同于 sandbox 已生效。
- 增加 child agent supervisor，提供 `spawn`、`status`、`wait`、`cancel`、`close` 和 heartbeat/lease 生命周期，并绑定 exact Graph/activity/attempt identity。
- 将 turn、tool request/attempt、approval、context compaction、child agent 和 worker status 统一投影为脱敏、可回放的 runtime events；canonical durable event history 仍是唯一权威。
- 增加进程重启、超时、取消、结果不确定和副作用幂等性的对抗测试与 release evidence。
- 将现有 OpenSpec 收口分流：立即完成 `model-aware-llm-context-preflight`；补齐 `source-policy-contract-convergence` 的真实 composition 缺口；保留 `durable-event-runtime` 和 `harness-workflow-graph-runtime` 的外部生产资格阻塞，不伪造签名或部署证据。

## Capabilities

### New Capabilities

- `execution-environment-runtime`: Defines Harness-authorized physical execution boundaries and fail-closed capability admission for tools and external workers.
- `child-agent-supervision`: Defines bounded child-agent lifecycle, leases, cancellation, recovery, and parent/child authority boundaries.
- `runtime-event-projection`: Defines the unified redacted runtime event projection for turns, tools, approvals, compaction, workers, and child agents.

### Modified Capabilities

<!-- Existing Graph, durable-event, tool, and context contracts remain authoritative. This change adds adapters and projections without replacing their existing owners. -->

## Impact

- Framework: `framework/tool`, `framework/harness/subagents`, `framework/harness/context`, `framework/harness/control_plane`, and runtime event contracts.
- Infrastructure: platform-specific process/sandbox adapters, process-tree termination, filesystem/network enforcement, and durable runtime event projections.
- Interfaces: operator status, wait, approval, cancellation, reconnect/resume, and safe timeline inspection.
- Tests: security boundary, restart/recovery, timeout/indeterminate outcome, idempotency, Graph identity, redaction, and cross-surface composition tests.
- Delivery: the four active OpenSpec changes remain separate owners; this change consumes their verified contracts and records whether each remaining task is repository work or external release qualification.
