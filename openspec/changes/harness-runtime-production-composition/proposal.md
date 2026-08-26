## Why

`ExecutionEnvironment`、`ChildAgentSupervisor` 和 runtime event projection 已经具备可用的契约、校验和单元测试，但它们仍主要作为可选端口存在于局部模块中。默认的 `AgentRunner`、Harness tool activity、Research sidecar、child dispatch 和 API operator read path 尚未共享同一套生产装配，因此一个真实运行可能安全地 fail closed，却不能像 Codex 一样在默认入口中执行、恢复、重连和审计。

现在需要把“已实现的能力”提升为“默认主链路能力”：让 Harness 继续作为 control plane，LLM 只生成候选内容，同时让文件、网络、环境变量、子进程、child 生命周期和运行时事件拥有单一、可持久化、可恢复的 owner。

## What Changes

- 新增 `RuntimeExecutionComposition`（名称可在设计阶段调整）作为默认生产 composition root；每个进程从同一份 versioned manifest 解析一致的 policy/provider fingerprint，并显式装配 `ExecutionEnvironmentRegistry`、durable execution/side-effect receipt store、child lease store、`ToolExecutor`、`ChildAgentSupervisor`、durable event/outbox publisher、projection checkpoint 和 operator authorization service。
- 将所有生产工具、出站 MCP tool/sidecar 和直接子进程入口接入 Harness 控制的 `ExecutionEnvironment`；sandboxed/external activity 没有明确 provider 时必须在 admission 阶段 fail closed，不能回退到宿主进程。入站 MCP server 仍只负责 interface/auth/application-service routing，不成为 execution provider。
- 将 `ChildAgentSupervisor` 接入实际的 child-agent dispatch，成为 `spawn/status/wait/cancel/close/heartbeat/recover` 的唯一生命周期 owner；child launch/terminate 必须经 admitted `ExecutionEnvironment`，execution receipt 与 lease/attempt 双向绑定。
- 将 turn、tool、approval、compaction、child、worker、timeout、cancel 和 indeterminate outcome 通过 canonical runtime event publisher 写入 durable event runtime；durable store 原子分配 per-run sequence，projection/API 使用鉴权且版本化的 cursor 提供 status 和 timeline 查询。
- 增加 recoverable intent/outbox/receipt 状态机及跨模块 adversarial 验证：进程重启、超时、child 丢失、取消结果不确定、外部调用成功但 receipt 未写入、receipt 已写入但 terminal event 未发布、重复投递、重复副作用、跨进程恢复和 operator reconnect。
- 增加部署能力矩阵和 evidence 规则；Docker daemon、durable event store 或不支持的 capability 不得用 fake/in-memory 证据伪装成生产就绪。

## Capabilities

### New Capabilities

- `production-execution-composition`: 默认生产入口对执行环境、工具、sidecar 子进程和 capability admission 的统一装配与 fail-closed 行为。
- `child-agent-production-supervision`: 真实 child dispatch 的 Harness-owned 生命周期、lease、heartbeat、取消不确定性和重启恢复。
- `canonical-runtime-event-transport`: 从运行时事实到 durable event runtime、projection、cursor/reconnect 和 operator read path 的单一事件链。
- `runtime-recovery-qualification`: 对重启、超时、重复投递、未知结果和副作用去重的跨模块验收与部署资格证据。

### Modified Capabilities

<!-- Existing contracts remain compatible; this change adds production composition and qualification requirements without replacing their existing normative requirements. -->

## Impact

- 主要代码边界：`framework/execution_environment`、`framework/tool/runtime`、`framework/agent/loop`、`framework/harness/subagents`、`framework/events/runtime`、`interfaces/composition`、`interfaces/api`、`business/research/document` 以及 worker/CLI 入口。
- 需要为生产 composition 注入真实 durable store/provider；测试仍可使用 fake provider，但必须通过同一 port 和 identity checks。
- API runtime status/timeline 将从“可选、未装配时 503”变成由默认 composition 提供的可审计读路径；这是部署配置的行为变化，但不改变 Harness 的 Graph、gate、approval 和 publication authority。
- 依赖 `durable-event-runtime` 的外部发布资格、Docker daemon 和已有 Graph/TaskPlan 契约；本 change 不替这些外部批准签字。
- 旧 change 的状态作为输入而不是合并目标：`harness-runtime-execution-safety` 当前 23/28，`durable-event-runtime` 53/55，`harness-workflow-graph-runtime` 99/100，`model-aware-llm-context-preflight` 28/34；`source-policy-contract-convergence` 已 41/41 complete。
