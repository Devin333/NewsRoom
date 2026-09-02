## Why

2026-09-02 的 Harness/Research 审计确认了一个 P0 和一组 P1/P2 运行时缺陷：timeout/cancel 后的 activity 不能可靠落盘、TaskPlan recovery/retry 语义不一致、Tool/MCP/skill/memory 的确定性授权边界可被 metadata 或旁路削弱，以及 shared redaction 和若干 persistence/test oracle 破坏数据完整性或掩盖故障。

这些问题跨越现有 change owner，不能通过一个局部测试或一个新 compatibility layer 解决。本 change 建立统一修复范围、优先级、责任边界和验收证据；具体 implementation 仍应在拥有对应 contract 的模块和 OpenSpec 下完成。

## What Changes

- 关闭 Graph activity timeout/cancel/indeterminate 的 durable terminal result 和防重复 dispatch 缺陷。
- 统一 TaskPlan replacement、retryable reason code、gate registration、projection、replay 和 recovery 语义。
- 使 `ToolPolicy` 成为 Tool/MCP approval 的权威输入，并将远端 MCP risk metadata 视为不可信。
- 修复 shared/LLM redaction 的普通文本误伤和 typed numeric field 损坏。
- 禁止 skill candidate metadata 自带 approval evidence，统一 MemoryRuntime mutation 的 policy enforcement。
- 为 serial side-effect recovery、lifecycle/resource retention、artifact/schema integrity、event diagnostics 和测试 oracle 建立 P2 收口队列。
- 将每项 finding 的 production reachability 区分为 runtime、framework contract 或 coverage gap，避免把未接线 API 误报为现有线上事故。

## Capabilities

### New Capabilities

- `framework-runtime-audit-repair`: Defines the priority, ownership, invariants, verification evidence, and release conditions for closing the 2026-09-02 Harness/Research audit findings.

### Modified Capabilities

- `execution-environment-runtime`: Adds durable timeout/cancellation/indeterminate result handling and no-redispatch recovery rules.
- `harness-runtime`: Adds TaskPlan recovery/retry/gate consistency and deterministic side-effect recovery constraints.
- `tool-governance`: Makes policy-owned approval and operator-owned MCP classification authoritative.
- `harness-skill-evolution` and memory runtime: Prevent candidate-controlled promotion evidence and policy-bypassing mutations.

## Impact

- Framework: `framework/harness/runtime`, `framework/harness/task_plan`, `framework/tool`, `framework/shared`, `framework/llm`, `framework/memory`, `framework/harness/skills`, and associated replay/recovery ports.
- Infrastructure/interfaces: only through existing application-service and composition boundaries; no interface may reach directly into executor/store authority.
- Tests: real dispatcher timeout/recovery, TaskPlan runner/replay, Tool/MCP behavior, redaction vectors, policy matrices, side-effect crash recovery, and architecture/test-oracle scans.
- Delivery: `harness-runtime-execution-safety` remains the owner for existing runtime qualification tasks. This change does not manufacture deployment evidence or mark its open tasks complete.

## Non-goals

- Replacing the Graph scheduler, workflow compiler, or bounded `PLAN -> EXECUTE -> VERIFY` model.
- Turning dynamic Research into a distributed planner, or granting LLMs routing, quality, authorization, publication, skill, or memory authority.
- Shipping a fake provider, approval record, evaluation result, or host-process fallback as a production safety solution.
- Treating every P2 framework/public-API issue as a current production incident without caller evidence.
