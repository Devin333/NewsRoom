## Context

NewsRoom 当前的 `ToolPolicy`、approval、timeout、retry、redaction 和 Graph identity 已经能够判断一次调用是否被允许，并由 `ToolExecutor` 记录逻辑执行事实。但 `ToolSandbox` 当前只执行 policy check，注册的 Python executor 仍可能直接在应用进程内运行；这不能证明文件系统、网络、环境变量和子进程已经受到物理限制。

NewsRoom 的 `SubAgentRuntime` 已有 Graph identity、输入输出 gate、transcript 和恢复证据，但主要以同步 `invoke()` 表达 worker 调用。`framework/events`、AgentLoop、approval、context compaction 和 worker service 也各自有事件或状态模型，缺少一个供 operator 使用的统一 runtime projection。

本设计必须服从现有边界：Graph/Harness 拥有 routing、budget、quality、approval、memory、publication 和 replay authority；LLM、tool、worker 和 child agent 只能产生候选、观察和证据。canonical durable event history 是事实来源，projection 不能反向驱动 workflow。

## Goals / Non-Goals

**Goals:**

- 让每次需要物理隔离的 tool/worker execution 都经过 Harness-controlled `ExecutionEnvironmentPort`。
- 将 filesystem、network、environment、child-process 和 cancellation 约束变成可验证的 execution receipt，而不是只存在于 policy trace 中。
- 为 child agent 提供有界、可恢复、幂等的 `spawn/status/wait/cancel/close/heartbeat` 生命周期。
- 用一套脱敏、带 Graph identity 和 checksum 的 runtime event projection 汇总 turn、tool、approval、compaction、worker 和 child-agent 状态。
- 在 provider 不具备所需物理能力时 fail closed，并能明确区分 `rejected`、`timed_out`、`cancelled` 和 `indeterminate`。
- 将现有四个 OpenSpec 的仓库内验证和外部 release qualification 分开记录。

**Non-Goals:**

- 不替换 Graph scheduler、`PLAN -> EXECUTE -> VERIFY`、quality gate、side-effect authority 或 durable replay。
- 不让 LLM 决定 routing、quality pass/fail、publication、memory write、skill promotion 或 tool authorization。
- 不在本 change 中实现新的模型 provider、MCP server、Research business workflow 或完整的跨云 container platform。
- 不把“in-process Python call”默认视为 sandbox；只有显式标记为 trusted pure function 的工具才可保留该执行模式。

## Decisions

### 1. Split logical policy from physical execution

新增 `ExecutionEnvironmentPort`，放在 framework contract 中；具体 provider 放在 infrastructure。`ToolExecutor` 负责 identity binding、policy、approval、budget、redaction 和 retry，但不直接为需要隔离的工具调用注册 executor。

标准请求包含：`GraphExecutionIdentity`、activity/attempt identity、`tool_id`、execution mode、argv/entrypoint、cwd、read/write roots、network policy、environment allowlist、resource limits、cancellation deadline 和 approval evidence ref。请求不得携带 raw secret。

标准 receipt 至少包含：execution id、status、start/end time、termination confirmation、exit code、reason code、output refs、capability profile 和 exact attempt identity。只有 receipt 已经绑定当前 activity/attempt，Harness 才能接受 worker result。

工具执行模式固定为两类：

- `trusted_in_process`：仅限 framework-owned、无文件/网络/子进程副作用的纯函数；不能读取任意 process environment。
- `sandboxed_process`：所有外部命令、解析器、网络、文件写入或不可信依赖必须使用该模式。

provider 必须声明能力。当前 Windows provider 可使用 `pywin32` Job Object 约束进程树和终止；strict filesystem/network policy 需要已部署且可证明的 OS/container provider。provider 不支持请求中的某项能力时，返回 `execution_environment_unavailable`，不得降级成普通进程调用。

### 2. Make restrictions inherited and fail closed

filesystem 使用 canonical roots，拒绝 drive-relative、UNC、traversal、越界 symlink/junction 和未声明的 read/write path；子进程继承同一边界。network 默认 deny，allowlist 只允许 provider 能够证明实际生效的 host/port policy。environment 默认空集，仅注入声明的非 secret 变量和由 `SecretProvider` 解析的命名 secret handle。

取消使用 bounded sequence：request cancel -> grace period -> terminate process tree -> verify termination。若 provider 无法确认进程树已经停止，receipt 必须为 `indeterminate`；任何带副作用的 indeterminate execution 禁止自动 retry。

### 3. Supervise child agents as leased runtime resources

新增 `ChildAgentSupervisor` 和不可变 `ChildAgentHandle`。handle 绑定 parent Graph identity、child id、stage/task/attempt、allowed tools/memory namespaces、budget 和 transcript ref。状态机至少包含 `STARTING`、`RUNNING`、`WAITING`、`SUCCEEDED`、`FAILED`、`CANCEL_REQUESTED`、`CANCELLED`、`LOST` 和 `CLOSED`。

`spawn` 必须经过 Harness admission；`status` 和 `wait` 只读；`cancel`、`close` 必须幂等；heartbeat 更新 lease；过期 lease 只能由 supervisor 标记 stale/reclaim，不能由 child 自己恢复。父进程重启时，supervisor 先从 durable event/transcript 恢复 handle，再决定 reattach、wait 或 fail closed，不能无条件重复执行副作用。

child output 只能是 candidate/evidence/result，不得包含 routing、quality、publication、memory-write、skill-promotion 或 sibling-control 字段。

### 4. Use one canonical event source and one safe projection

runtime event 统一写入现有 canonical durable event port，采用稳定 event identity、Graph/activity/attempt identity、schema revision、sequence、occurred/observed timestamps、reason code、status、refs/checksums 和 redacted metadata。raw prompt、secret、完整 tool payload、文件内容和未授权 evidence body 不进入普通事件。

事件类别覆盖：turn start/stop/abort、tool requested/approval/started/terminal、child spawn/status/heartbeat/terminal、context compaction plan/commit/reject、worker status 和 runtime error。projection 使用 event identity 幂等，通知可以 at-least-once；projection 落后或重建不能改变 scheduler decision。

operator API 读取 projection，并支持 bounded cursor/resume、按 Graph/activity/attempt 过滤、解释 waiting/failed/indeterminate 原因。任何写操作仍走现有 application service 和 Harness wait/approval/cancel port。

### 5. Treat current OpenSpec work by evidence class

- `model-aware-llm-context-preflight`：核心实现已完成，先完成 focused tests、compile、smoke、strict validation、审计和 path-scoped commit。
- `source-policy-contract-convergence`：补真实 API/MCP/worker/CLI/tool/Harness/Research composition、连续 quota、typed no-network denial 和 evidence；不得只更新 checkbox。
- `durable-event-runtime`：代码契约可被新 change 消费，但 `9.5` 的外部治理签名、真实部署观察和独立 rollback qualification 不能由本地代码伪造；保持 blocked/in-progress。
- `harness-workflow-graph-runtime`：代码层依赖已满足，唯一未完成项受 durable 外部资格阻塞；不重复实现，保持待 release qualification。

## Risks / Trade-offs

- [平台能力不一致] Windows 本地、Linux host 和 container 对网络/文件隔离能力不同 -> provider 公开 capability profile，不能满足要求就 fail closed，并按 deployment 记录支持矩阵。
- [取消后结果不确定] 进程可能在 grace period 后仍持有副作用 -> 使用 `indeterminate` receipt，禁止有副作用自动重试，要求人工或专用 reconciliation。
- [事件量和敏感数据增加] tool output、路径和错误信息可能泄露数据 -> durable write 前统一 redaction，普通事件只保留 refs/checksums，敏感 payload 使用独立授权存储。
- [长任务开销] heartbeat、lease 和 projection 会增加 I/O -> 使用 bounded interval、批量只读 projection 和 durable event consumer checkpoint，不牺牲 canonical append。
- [旧入口绕过 Harness] 直接构造 executor 或 standalone Research composition 会削弱边界 -> 架构测试扫描 production caller，未绑定 provider 的隔离能力请求统一拒绝。

## Migration Plan

1. 先完成 context preflight 的本地交付验证，并修复 Source composition 的真实入口缺口；记录 durable/Graph 外部资格状态。
2. 引入 `ExecutionEnvironmentPort`、能力 profile、receipt 和 trusted/sandboxed execution classification；未绑定 provider 的 sandboxed tool 先 fail closed。
3. 将 ToolExecutor 的 sandboxed path 接到 provider，先覆盖文件、环境、子进程和取消，再启用严格 network profile。
4. 引入 child supervisor，迁移 AgentLoop/SubAgent activity 到 handle/lifecycle contract，保留 transcript 作为 evidence，不改变 Graph scheduler authority。
5. 接入 canonical runtime event projection 和 operator read API，提供 cursor/resume 与 redacted timeline。
6. 通过对抗测试、进程重启演练、indeterminate side-effect 演练和全量 OpenSpec validation 后，才开放对应 deployment profile；失败时关闭新 execution profile，不回退到未隔离执行。

## Open Questions

- 生产 deployment 的 strict network provider 是 OCI/container 还是宿主机原生 provider，需要在部署配置中选择并提交 capability evidence；这不改变 framework port 或 fail-closed contract。
