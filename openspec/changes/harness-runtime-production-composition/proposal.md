## Why

`ExecutionEnvironment`、Docker provider、execution profile 与 capability admission 已经有可复用的契约，但若干生产入口此前只构造本地 `ToolExecutor` 或把 provider 作为可选依赖传递。因此安全模型存在，却没有稳定地进入默认执行路径。

本 change 只解决 production execution wiring：Harness 继续是 control plane，LLM、worker 与 parser 只产生 candidate 或 observation。它不重新定义 child lifecycle、durable event、approval、业务 side-effect authority 或跨系统 recovery。

## What Changes

- 提供轻量、进程本地的 `RuntimeExecutionComposition` factory。每个入口独立创建对象，但从同一份配置、policy 与 provider profile 解析一致的 composition identity；不引入跨进程 manifest 服务，也不将 durable event 或 child repository 伪装成 execution composition 的必需端口。
- 将 execution registry/profile 与 `ToolExecutor` factory 注入 `AgentRunner`、Harness tool activity、batch executor、API、worker、CLI 和 Research composition。只有选定的 Research PDF parser 在本切片启用 external-process production profile；其余入口先验证接线与 fail-closed compatibility。
- 将选定的 Research Marker/MinerU PDF parser 收敛到 `ResearchParserExecutionAdapter`。adapter 只映射 argv、cwd、read/write roots、allowlisted environment、timeout、cancellation 和 `ExecutionReceipt`；它不拥有 Graph routing、publication 或业务 side-effect decision。
- 对 `sandboxed` 与 `external_process` activity 强制 profile、Graph identity、capability、provider 与 termination contract admission。缺失或不支持时返回稳定 typed denial，禁止宿主进程 fallback；`trusted_in_process` 仅允许显式注册的纯函数。
- 维护 Harness-managed external-process caller inventory 与静态检查。Docker provider 内部启动、tests、build/development tooling 与暂未选中的 PDF compiler 记录为明确豁免或后续迁移项，而不是被静默忽略。
- 记录 Docker/provider capability、测试命令与 blocked qualification evidence。Docker 不可用时，Research parser 保持 typed blocked，不把 local contract test 描述为真实 sandbox qualification。

## Scope Handoff

下列能力由独立 change 继续交付，不属于本 change 的 completion claim：

- 真实 child dispatch、lease、heartbeat、restart recovery：`harness-child-supervisor-integration`。
- canonical durable event、projection cursor、operator reconnect：`durable-event-runtime` 与 `runtime-event-operator-wiring`。
- intent/outbox/reconciliation、跨系统 exactly-once、production rollback qualification：`runtime-recovery-qualification`。
- outbound MCP/sidecar 的业务纵向切片：在其选择真实调用场景后单独提案。

## Capabilities

### New Capabilities

- `production-execution-composition`: 生产 execution composition、显式 activity profile、受控 Research parser adapter、caller inventory 与 fail-closed qualification evidence。

### Modified Capabilities

<!-- Existing Harness, child, durable event, approval, artifact, and side-effect contracts remain owned by their current changes. -->

## Impact

- 主要代码边界：`framework/execution_environment`、`framework/tool/runtime`、`framework/agent/loop`、`interfaces/composition`、`interfaces/api`、worker/CLI 入口与 `backend/research/document`。
- API、worker、CLI、Harness 与 Research 共享 execution policy/config identity，但不共享 Python provider 对象，也不由本 change 接管 event/child/approval authority。
- 真实 Docker qualification 仍取决于目标环境 daemon 与能力声明；本地 Docker 缺失只能证明 fail-closed blocked 行为。
