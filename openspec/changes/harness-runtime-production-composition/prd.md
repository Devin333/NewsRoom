# NewsRoom Harness Runtime Production Composition PRD

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| Change | `harness-runtime-production-composition` |
| 优先级 | P0/P1/P2 |
| 状态 | Draft，待实现 |
| 产品原则 | LLM as worker, Harness as control plane |
| 目标 | 把已有运行时安全组件接入默认生产主链路 |

## 2. 背景与问题

当前 NewsRoom 已经实现了三类关键能力：

- `ExecutionEnvironment` 已有请求模型、capability admission、Docker provider、超时/终止回执和 fail-closed 校验。
- `ChildAgentSupervisor` 已有 `spawn/status/wait/cancel/close/heartbeat/recover`、lease、预算和幂等语义。
- runtime event projection 已能规范化 turn、tool、approval、child、worker、timeout、cancel 和 indeterminate outcome，并支持 cursor/rebuild。

但是这些能力尚未成为默认生产路径。当前主要问题是：

1. `AgentRunner`、Harness tool activity 和部分 Research sidecar 仍没有注入真实 `ExecutionEnvironment`；sandboxed 工具可能因为缺 provider 而安全失败，但不会自动进入真实隔离环境。
2. 实际 child dispatch 仍可能走旧的 `SubAgentRuntime`；`ChildAgentSupervisor` 还没有成为所有生产 child 生命周期的唯一 owner。
3. runtime event sink、projection 和 API operator service 仍是可选注入；默认入口没有保证 durable event、重启恢复和 cursor reconnect。
4. 直接调用 `subprocess.run` 的 parser/sidecar 入口可能绕过同一套文件、环境变量、网络、子进程和取消策略。
5. 当前测试主要验证 contract、fake provider 和 in-memory store，尚不足以证明真实进程重启、超时、child 丢失、取消不确定和副作用不重复执行。

因此，当前与 Codex 的主要距离不是缺少类或接口，而是缺少“默认生产 composition”：Codex 把 sandbox、approval、session/turn 事件和 child 生命周期放在实际 app-server/core 运行路径中；NewsRoom 仍有一部分能力停留在可选端口和局部测试层。

## 3. 产品目标

### 3.1 P0：默认生产执行隔离

建立 versioned `RuntimeCompositionManifest`；API、worker、CLI、Harness 和 Research 各进程据此创建自己的 `RuntimeExecutionComposition`，并验证一致的 policy/provider fingerprint。所有外部工具、parser、compiler、出站 MCP adapter/sidecar、child 和其他子进程必须经过 Harness 控制的 execution environment。

生产默认行为必须是：

- sandboxed/external activity 没有匹配 provider、Graph identity、capability 或 policy 时，admission 直接拒绝；
- 不得因 provider 未配置而静默回退到宿主进程执行；
- 文件根目录、读写 mount、网络策略、环境变量 allowlist、argv、子进程数量、超时和取消都必须出现在 `ExecutionRequest` 与 `ExecutionReceipt` 中；
- provider 不支持的 capability 必须显式拒绝，而不是降低安全等级继续运行。

### 3.2 P1：Harness-owned child agent

将 `ChildAgentSupervisor` 接到真实的 child-agent dispatch。Harness 是 child 的生命周期 owner，LLM/worker 只能返回候选结果，不能决定 spawn、routing、approval、retry、close 或 publication。

必须支持：

- 通过稳定 `parent_run_id`、`child_id`、`lease_id`、Graph identity 和 attempt identity 进行追踪；
- `spawn/status/wait/heartbeat/cancel/close` 的幂等调用和权限检查；
- 父进程重启后从 durable lease/transcript/event 恢复；
- child launch/terminate 必须经 admitted `ExecutionEnvironment`，且 execution receipt 与 lease/attempt 双向绑定；
- 心跳超时、child 丢失、取消结果不确定时进入 `LOST`/`INDETERMINATE` 等受控状态；
- 恢复过程中不得重复执行已经提交的副作用。

### 3.3 P1：统一 durable runtime event

所有运行时事实通过 canonical publisher 写入现有 durable event runtime：turn 开始/结束、LLM 调用、tool 调用/观察、approval 请求/决定、compaction、child 生命周期、worker heartbeat、timeout、cancel、indeterminate 和 terminal outcome。

durable store 按 run 原子分配 monotonic sequence。operator 只能在 authenticated principal/tenant scope 内读取 projection，不得修改 Graph state、approval、side-effect authorization 或 worker result。API/MCP/CLI 的状态查询必须支持绑定 run/Graph/schema/principal fingerprint 的 bounded cursor、重连和跨 run 隔离；approval decision 只能经 Harness approval service 写入 authoritative receipt/outbox。

### 3.4 P2：恢复与发布资格

补齐跨模块验证和部署证据，覆盖：

- 进程重启与 durable recovery；
- execution timeout、termination confirmation 和子进程清理；
- child loss、heartbeat timeout 和 ambiguous cancellation；
- duplicate delivery、retry 和副作用 dedupe；
- intent/outbox/receipt 状态机每个 crash point 的唯一恢复分支；
- event cursor reconnect、projection rebuild 和重复事件幂等；
- Docker daemon、durable event store、secret handle、network allowlist 等 capability 的真实部署矩阵。

## 4. 用户与现实场景

### 场景 A：Research 解析 PDF

Research worker 请求 PDF parser。Harness 根据 Graph identity 和 tool policy 生成 `ExecutionRequest`，由 Docker provider 挂载只读输入目录和受控输出目录，禁止默认网络，设置 timeout/pids limit，并返回带 checksum 的 `ExecutionReceipt`。parser 失败时只产生受控失败事件，不会把宿主机环境变量或任意目录暴露给 parser。

### 场景 B：长时间 child analysis

父 run spawn 一个 child agent 做证据整理。父进程重启后，supervisor 读取 durable lease 和最后 heartbeat，判断 child 是可恢复、已完成、已丢失还是结果不确定。若 side effect receipt 已提交，恢复逻辑读取原 receipt；若没有 terminal evidence，则进入 quarantine/retry/manual repair，不能直接再次执行。

### 场景 C：operator 断线重连

operator 已读取到 cursor `c1`，网络断开后使用 `after=c1` 重连。API 从 durable event runtime 继续返回同一 run 的事件，重复 event 不造成重复 projection；跨 run cursor、未授权 run 和超出 limit 的请求都被拒绝或截断。

## 5. 范围与需求

### P0-ENV：生产执行环境

- 提供唯一 composition root，禁止各入口自行创建互不相同的 provider/registry。
- 为 `AgentRunner`、Harness activity runtime、batch executor、Research parser/PDF compiler、worker、CLI 和出站 MCP `ToolRuntime` path 注入 fingerprint 一致的执行环境端口；入站 MCP server 只调用 application service。
- 对 `trusted_in_process`、`sandboxed`、`external_process` 做显式分类；默认外部活动必须有明确 profile。
- 将 `subprocess.run` 等直接子进程调用迁移到受控 adapter，保留业务接口但移除旁路执行。
- 生产不允许以 in-memory provider/store 代替真实 capability；测试 fake 必须实现同一 contract。

### P1-CHILD：child supervisor

- 统一 child dispatch owner，兼容现有 Graph/TaskPlan identity。
- durable lease、heartbeat、attempt receipt、transcript/output ref 和 lifecycle event 必须绑定同一 parent/child scope。
- 明确 cancel 的三种结果：已确认终止、未确认终止、不可达/丢失；后两者不得报告普通成功。
- `close` 必须是幂等且可审计的 terminal operation；恢复不得绕过 supervisor。
- durable lease/heartbeat/receipt/transcript/idempotency repositories 必须由 composition 显式注入；生产不得使用 in-memory backing。

### P1-EVENT：canonical event transport

- canonical event publisher 是唯一运行时事实入口；projection 是下游读模型，不得成为第二事件权威。
- 事件包含稳定 event id、run/parent/child scope、Graph identity、attempt、occurred_at、sequence、payload checksum、redaction metadata。
- publisher、durable store、projection 和 operator read service 必须支持重放、幂等和 bounded cursor。
- approval、compaction、worker status 等事件不得只记录在日志或内存对象里。
- approval `requested/decided/rejected/expired` 只能由 Harness approval service 经 deterministic authorizer、幂等 receipt 和 canonical outbox 写入。

### P2-QUAL：验证与部署证据

- 集成测试覆盖真实 provider contract 和所有 caller scan；在 Docker 不可用的主机上必须明确标记 skip/blocker，不能伪造通过。
- adversarial 测试验证 crash/restart、timeout、child loss、ambiguous cancel、duplicate event、side-effect dedupe、cross-run isolation 和 reconnect。
- 生成 capability matrix、测试命令、结果、环境条件、已知不支持项和 rollback evidence。

## 6. 非目标

- 不重写 `HarnessGraph`、TaskPlan、deterministic gate 或 publication authority；它们继续由 Harness 控制。
- 不让 LLM 决定 workflow routing、quality pass/fail、tool authorization、approval、memory write 或 publication。
- 不把 `durable-event-runtime` 与 `harness-workflow-graph-runtime` 尚未取得的外部发布签名伪装成本 change 的本地完成条件。
- 不用 fake sandbox、日志字符串、调用方布尔值或 in-memory store 冒充生产隔离和 durable recovery。
- 不在本 change 内同时收口 `model-aware-llm-context-preflight` 或 `source-policy-contract-convergence` 的独立剩余任务；它们作为前置依赖分别验收。

## 7. 验收标准

| ID | 验收条件 | 证据 |
| --- | --- | --- |
| AC-ENV-01 | 默认生产 composition 为所有外部 activity 提供 fingerprint 一致的 registry/provider policy | composition 集成测试、manifest drift test、caller scan |
| AC-ENV-02 | provider 缺失、capability 不支持、Graph identity 不匹配时 fail closed | negative tests、typed denial |
| AC-ENV-03 | parser/sidecar 无法绕过 execution environment | subprocess caller inventory + integration test |
| AC-CHILD-01 | 实际 child dispatch 只通过 `ChildAgentSupervisor` | dispatch path test、唯一 owner scan |
| AC-CHILD-02 | child launch/terminate 经过 execution provider，restart/heartbeat/cancel/close 的 receipt 可恢复、可重放 | durable recovery tests + execution receipt binding |
| AC-EVENT-01 | 所有 runtime fact 进入 durable canonical stream，sequence 由 store 按 run 原子分配 | event contract + concurrent publisher test |
| AC-EVENT-02 | API operator 先鉴权再读，并支持绑定 scope/principal 的 cursor reconnect | API integration test + authorization audit |
| AC-REC-01 | intent/outbox/receipt 覆盖 crash point，duplicate delivery 与 side-effect retry 不产生重复提交 | crash matrix + idempotency/reconciliation tests |
| AC-QUAL-01 | capability matrix 明确 Docker/durable store/unsupported capability 的真实状态 | deployment evidence |
| AC-QUAL-02 | strict validation、compile、focused tests 和适用 smoke 有记录，并区分 contract pass 与 qualification blocker | evidence.md / CI artifact |

## 8. 依赖与前置条件

本节的数字是 `2026-08-26`、baseline `0ed5ee0b` 的快照，不是自动更新的实时状态。依赖的 hard/contextual/external 分类以 10.6 为准：旧 safety change 负责低层契约验收的完成或显式 handoff；durable event 的外部签名只阻断 production qualification；Graph 和 model-aware change 并行推进；已 41/41 的 Source change 是完成基线，不重新打开。

Docker daemon、durable event store、生产 secret/credential provider 和部署观察者必须在发布环境中可验证；缺少其中任一能力时记录 typed blocker，不得以本地 fake 或 in-memory 结果替代。

## 9. 发布与回滚

采用 capability-gated rollout：先以 shadow mode 记录/比较 execution/event composition 计划但不启动 external activity 或副作用，再对选定 Graph activity 启用 provider，最后启用 child recovery 和 operator reconnect。旧路径在灰度期间只允许 inventory 中已验证的 pure `trusted_in_process` activity；sandboxed/external activity 没有真实 provider 时保持 typed blocked。每一步都必须有 typed denial 和可查询 event。

若新 composition 或 provider 出现故障，回滚只允许回到已批准的旧 composition，并保留已提交的 execution receipt、child lease 和 canonical event；不得通过删除 event、清空 projection 或重复执行 side effect 来“恢复”。未取得真实 provider/外部治理资格时，功能保持 disabled/blocked，而不是降级成无隔离模式。

## 10. 运行时一致性与授权边界

### 10.1 Composition identity 和 durable ports

每个进程创建自己的 `RuntimeExecutionComposition` 实例，但必须从同一份 versioned manifest 解析相同的 `composition_id`、policy fingerprint、provider/config identity、event schema 和 durable-store contract。这里要求跨进程配置一致，不要求共享 Python 对象。

composition 必须显式注入以下生产 ports：execution registry、execution/side-effect intent 与 receipt repository、child lease/heartbeat/transcript/output/idempotency repository、canonical event store/outbox、projection checkpoint store、operator authorizer 和 operator read service。生产 profile 解析到 in-memory backing 时必须 typed blocked。

### 10.2 外部调用、receipt 与 event 的崩溃一致性

每个已授权 external side effect 在 dispatch 前写 immutable intent 与 idempotency key，状态机固定为：`PREPARED -> DISPATCHED -> RECEIPT_COMMITTED -> EVENT_PUBLISHED`。provider 或 reconciliation port 必须能够使用同一 key 查询结果；receipt 是外部执行结果的 authoritative record，terminal event 通过可重试 outbox 发布。

| 崩溃位置 | 唯一允许的恢复动作 |
| --- | --- |
| `PREPARED`，没有 dispatch 证据 | 使用原 identity/key 执行一次 |
| `DISPATCHED`，没有 receipt | 查询 provider/reconciliation；无法确认则 `INDETERMINATE`/quarantine，不重发 |
| `RECEIPT_COMMITTED`，没有 event | 仅补发 outbox event，不再调用外部 handler |
| transition/checksum 冲突 | 进入 typed integrity conflict/quarantine，不前进状态 |

### 10.3 Child execution 与 durable state

生产 child launch/terminate 必须消费 admitted `ExecutionRequest`，返回的 `ExecutionReceipt` 与 child lease/attempt 双向绑定。`ChildAgentSupervisor` 是唯一 lifecycle owner，且其 lease、heartbeat、receipt、transcript/output reference 和 idempotency repository 必须 durable、可跨进程读取、带 immutable checksum、parent/child access scope 与 retention owner。若加密、跨进程锁或 retention binding 尚未具备，cross-process recovery 只能标为 qualification-blocked。

### 10.4 Event、cursor、operator 与 approval

durable event store 对每个 run 原子分配 monotonic sequence，并强制 `(run_id, sequence)` 唯一。相同 event id/checksum 幂等返回原 receipt；相同 id 但不同 payload、或并发 sequence 冲突必须返回 typed conflict。cursor 编码 schema version、run/Graph scope、last sequence 和 authenticated principal/tenant fingerprint；服务先鉴权后读取，只返回 redacted bounded refs，并记录 bounded authorization audit。

approval 的 `requested/decided/rejected/expired` 必须经 Harness approval application service、deterministic authorizer、approval/Wait scope、idempotency key、authoritative receipt 和 canonical outbox 写入。operator 与 worker 没有 approval-decision write capability，只有 Harness 能提交 resume transition。

### 10.5 MCP 与 caller inventory

入站 MCP server 是 interface/auth/application-service routing，不是 execution provider；只有出站 `ToolRuntime` MCP adapter 和本地 sidecar 进入 execution admission，并显式声明 network、credential handle、timeout 和 cancellation capability。

`subprocess` caller scan 只覆盖生产业务/基础设施运行包，不覆盖 tests、开发工具和 build tooling。每个豁免必须进入 versioned inventory，包含 owner、理由、非 Harness-managed 证明、到期/复核日期及对应静态检查或测试；CI 默认拒绝新增未登记 caller。

### 10.6 依赖分类

| 依赖 | 分类 | 处理方式 |
| --- | --- | --- |
| `harness-runtime-execution-safety` 5.1-5.4 | Hard prerequisite / handoff | 先完成或显式交接集成、scan、strict/compile/smoke 与 capability evidence；本 change 不重复勾选旧任务。 |
| `durable-event-runtime` 53/55 | External qualification blocker | 复用 event port；外部签名、部署观察和 rollback 资格缺失时，本 change 只能 qualification-blocked。 |
| `harness-workflow-graph-runtime` 99/100 | Parallel, evidence-only | 复用 Graph contract，不把外部 cutover 资格当成本 change 完成条件。 |
| `model-aware-llm-context-preflight` 28/34 | Contextual prerequisite | 共享 LLM/router 路径变更前需完成 focused verification；不触及该路径时不阻断文档/契约阶段。 |
| `source-policy-contract-convergence` 41/41 | Completed baseline | 复用完成的 Source composition/quota contract，不重新打开其范围。 |

### 10.7 Evidence 和迁移约束

本 change 维护 `evidence.md`，每次记录 commit/date、环境、manifest/provider fingerprint、durable-store capability、命令、pass/skip/block、真实 receipt/event refs 和外部签名状态。contract/fake/in-memory pass 只能证明契约，不得标记为真实隔离、跨进程 durable recovery 或 production qualification。

shadow mode 只记录/比较 admission 和 event 计划，绝不启动 external activity 或副作用。灰度期旧路径只允许 inventory 中已验证的 pure `trusted_in_process` activity；sandboxed/external activity 缺少真实 provider 时保持 typed blocked，不能沿用宿主进程旁路。

## 11. Definition of Done

- 所有新 capability spec、design、tasks 和本 PRD 通过 `openspec validate harness-runtime-production-composition --strict`。
- 默认 API/worker/CLI/Harness/Research composition 具备真实 provider 和 durable event wiring，或在启动/admission 时明确 typed blocked 状态。
- caller scan 证明没有未豁免的 direct subprocess、绕过 supervisor 的 child dispatch 或第二事件权威。
- AC-ENV、AC-CHILD、AC-EVENT、AC-REC、AC-QUAL 全部有可追溯测试/证据；外部发布资格缺失项明确列为 blocker，不被勾成完成。
