# NewsRoom Harness Runtime Execution Safety PRD

## 1. 文档信息

| 字段 | 内容 |
|---|---|
| 产品/能力 | Harness Runtime Execution Safety and Supervision |
| OpenSpec Change | `harness-runtime-execution-safety` |
| 状态 | Draft for implementation |
| 日期 | 2026-08-25 |
| 目标版本 | Harness Runtime Safety v1 |
| 产品原则 | `LLM as worker, Harness as control plane` |

## 2. 背景

NewsRoom 的业务 Harness 已经能控制 Graph routing、`PLAN -> EXECUTE -> VERIFY`、deterministic gate、approval、side effect、durable event 和 replay。当前与 Codex Harness 的主要差距不在“有没有 allowlist”，而在三个运行时问题：

1. 工具获准调用以后，是否真的只能读写指定目录、访问指定网络、看到指定环境变量，并且能被可靠取消。
2. 子 Agent 启动以后，Harness 是否能知道它是否还活着、是否失联、是否需要等待、是否已经被取消，以及父进程重启后如何恢复。
3. turn、tool、approval、context compaction、worker 和 child agent 的状态是否能通过一个统一、脱敏、可回放的事件时间线观察。

## 3. 产品目标

### P0：ExecutionEnvironment

所有需要文件、网络、外部命令、解析器或不可信依赖的执行必须经过 Harness 控制的 `ExecutionEnvironment`。

执行环境必须能够表达并验证：

- 文件系统 read roots、write roots 和 canonical path containment；
- 默认拒绝网络以及显式 host/port allowlist；
- 默认不继承宿主进程环境变量；
- 只允许显式声明的子进程和 argv；
- process tree 的超时、取消、grace period 和终止确认；
- Graph/activity/attempt identity、approval evidence 和 execution budget。

如果当前 deployment 没有能力执行所要求的限制，Harness 必须返回 typed `execution_environment_unavailable` 并停止该 activity。禁止因为 policy 已经允许，就直接在普通应用进程内运行 sandboxed tool。

### P1：Child Agent Supervisor

Harness 必须将 child agent 作为有界、可恢复的运行时资源管理，提供：

```text
spawn -> status -> wait
                 |
                 +-> cancel -> close
                 |
                 +-> heartbeat / lease / reclaim
```

生命周期至少覆盖 `STARTING`、`RUNNING`、`WAITING`、`SUCCEEDED`、`FAILED`、`CANCEL_REQUESTED`、`CANCELLED`、`LOST`、`CLOSED`。

child agent 不得拥有 Graph routing、quality、publication、memory write、skill promotion 或 sibling control authority。

### P1：Runtime Event Projection

所有运行态事实必须映射到 canonical durable event，并提供安全的 operator projection。第一版事件范围包括：

- turn start/stop/abort；
- tool requested、approval requested/decided、execution started/terminal；
- child spawn/status/heartbeat/terminal；
- context compaction plan/commit/reject；
- worker heartbeat/status/lease；
- timeout、cancel、indeterminate 和 runtime error。

事件必须绑定 Graph/activity/attempt identity，带 schema revision、reason code、refs/checksums 和 redacted metadata。raw prompt、secret、完整 tool payload、文件内容和未授权 evidence body 不得写入普通 runtime event。

### P2：验证和发布收口

P2 不是继续堆功能，而是完成现有基础合约的验证分流：

| OpenSpec | 当前判断 | 本 PRD 的处置 |
|---|---|---|
| `model-aware-llm-context-preflight` 28/34 | 实现主干已完成，剩余为本地验证和交付 | 立即完成 focused tests、compile、smoke、strict、审计和 path-scoped commit |
| `source-policy-contract-convergence` 38/41 | 仍有真实入口 composition/额外测试缺口 | 补 API/MCP/worker/CLI/tool/Harness/Research 绑定、连续 quota、typed no-network denial 和 evidence |
| `durable-event-runtime` 53/55 | 剩余 9.5 是外部治理/真实部署/回滚资格，不是普通代码任务 | 保持 `in-progress/blocked`，不得伪造 D -> A -> B -> deploy -> C 证据；新 change 只消费已验证的代码契约 |
| `harness-workflow-graph-runtime` 99/100 | 代码层已完成，受 durable 外部资格连带阻塞 | 不重复实现、不强行勾选，等待上游 durable release qualification |

## 4. 用户与使用场景

### 4.1 Research worker 执行 PDF 解析

当 Research worker 请求解析 PDF 时：

1. Harness 验证工具、Graph identity、approval、budget 和 execution profile。
2. ExecutionEnvironment 只挂载本次 run 的论文目录和输出目录。
3. 解析进程只能看到声明的环境变量，默认不能访问网络。
4. 超时后先取消进程树，再确认是否终止。
5. 如果终止无法确认，结果为 `indeterminate`，Harness 不得自动重跑一个可能重复副作用的解析任务。

### 4.2 长时间 child agent

当主 Graph 启动 child agent 分析一组论文时：

1. Harness 返回带 exact identity 的 child handle。
2. operator 能查询 child 是否运行、等待、失败、失联或已取消。
3. child 必须按 heartbeat 更新 lease；过期后由 supervisor 标记 `LOST` 或执行受控 reclaim。
4. 父进程重启后，系统从 durable history 恢复 child 状态，不因重启自动产生第二次副作用执行。

### 4.3 运行观察

operator 打开一个 run 时，应能看到一条安全时间线：

```text
Graph activity started
  -> turn started
  -> tool approval requested
  -> approval accepted
  -> sandbox execution started
  -> child heartbeat stale
  -> cancellation requested
  -> termination confirmed
  -> VERIFY halted: child_lost
```

这条时间线用于解释和恢复，不用于让 UI 或 LLM 直接改变 Graph routing。

## 5. 范围与边界

### 包含

- framework-level execution environment contract、capability profile 和 receipt；
- infrastructure-level process/sandbox providers；
- ToolExecutor 到 ExecutionEnvironment 的接入；
- child agent supervisor、lease、recovery 和 lifecycle events；
- runtime event canonical schema、redacted projection、cursor/resume read API；
- P2 现有 OpenSpec 的本地验证、composition 修复、对抗测试和 release evidence。

### 不包含

- 重写 Graph scheduler 或替换 `PLAN -> EXECUTE -> VERIFY`；
- 让 LLM 选择 routing、quality、publication、memory 或 authorization；
- 新增 Research 业务流程或模型 provider；
- 在没有真实 provider 的环境中用 fake/no-op sandbox 伪装生产隔离；
- 伪造外部签名、部署观察、rollback qualification 或 trust activation evidence。

## 6. 核心验收标准

### ExecutionEnvironment

- 越界路径、drive-relative path、UNC path、traversal、symlink/junction escape 全部拒绝。
- 未声明的读写目录、网络 host/port、环境变量和子进程全部拒绝或不可见。
- 没有对应 provider capability 时 fail closed，并产生稳定 reason code。
- 超时和取消可区分“已确认终止”和“结果不确定”。
- `indeterminate` 的有副作用执行不会自动 retry。
- execution receipt 可通过 Graph/activity/attempt identity 与 durable event 对齐。

### ChildAgentSupervisor

- `spawn/status/wait/cancel/close` 均有明确 contract，重复调用幂等。
- heartbeat/lease 过期可以被 supervisor 识别并进入受控 `LOST`/reclaim 流程。
- 父进程重启后不会重复提交同一副作用结果。
- child 无法写入 routing、quality、publication、memory、skill 或 sibling-control 字段。
- child transcript、execution receipt 和 Graph identity 可以交叉校验。

### Runtime Event Projection

- tool、approval、turn、compaction、worker 和 child agent 都能映射到统一 event envelope。
- event 写入前执行 redaction，projection 按 event identity 幂等。
- operator 可按 run/node/activity/attempt 查询并用 cursor 恢复，不需要 raw payload。
- projection 重建或通知重复不会改变 scheduler、gate 或 side-effect authority。

### P2 交付

- `model-aware-llm-context-preflight` 完成其 7.1-7.6 并通过 strict validation。
- `source-policy-contract-convergence` 完成 3.7、3.10、7.5 的真实 composition 和证据。
- durable/Graph 两个外部 qualification blocker 被明确记录，未被测试 key、空 evidence 或文档声明替代。
- 进程重启、工具超时、child 失联、取消不确定和副作用重复执行测试通过。

## 7. 非功能要求

- 安全：默认 deny，能力不足 fail closed，普通 event 不得泄露 secret/raw payload。
- 可恢复：canonical event 是 source of truth，projection/checkpoint 只能加速恢复。
- 可测试：所有 provider capability、状态转换、reason code 和 identity mismatch 均可用 fake provider 验证；生产路径必须有真实 adapter contract test。
- 可观测：所有 execution、child、approval 和 compaction 的 terminal 状态都有稳定 reason code、duration 和 identity refs。
- 可移植：framework 不依赖具体 OS；平台限制由 infrastructure provider capability 明确表达。

## 8. 分阶段交付

1. **Phase 0：基础收口**。完成 context preflight；补 Source composition 和入口级 quota/no-network 证据；记录 durable/Graph 外部资格状态。
2. **Phase 1：P0**。落地 ExecutionEnvironment contract、provider capability、receipt、ToolExecutor 接入和安全对抗测试。
3. **Phase 2：P1**。落地 ChildAgentSupervisor、lease/recovery、cancel/close 和 lifecycle events。
4. **Phase 3：P1**。落地统一 runtime event projection、operator read API、cursor/resume 和 redaction tests。
5. **Phase 4：P2**。运行全量相关验证、进程重启演练、release evidence 和 deployment capability qualification。

## 9. 发布策略

- 新 sandboxed execution profile 默认关闭，直到真实 provider capability evidence 完成。
- 没有 provider 的环境只允许显式的 `trusted_in_process` pure function，不得隐式降级。
- 任一核心安全或恢复 gate 失败，停止新 profile；不回退到无隔离的普通 executor。
- durable/Graph 外部 release qualification 独立于本 change 的代码实现，由 deployment/release owner 完成。
