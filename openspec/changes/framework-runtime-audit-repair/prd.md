# NewsRoom Framework Runtime Audit Repair PRD

## 1. 文档信息

| 字段 | 内容 |
| --- | --- |
| 产品/能力 | Harness Runtime Integrity and Policy Repair |
| OpenSpec Change | `framework-runtime-audit-repair` |
| 状态 | Draft for implementation |
| 日期 | 2026-09-02 |
| 来源 | 2026-09-02 Harness/Research 审计发现汇总 |
| 产品原则 | `LLM as worker, Harness as control plane` |
| 发布目标 | 修复 P0/P1 运行时边界，并为 P2 建立可追踪的收口队列 |

本 PRD 是审计修复的产品合同，不等同于一次代码提交。它规定哪些缺陷必须在本修复计划中关闭、哪些条目应由现有 OpenSpec change 继续负责，以及如何用可重复的运行证据证明修复有效。

## 2. 产品摘要

审计发现集中在四类边界失效：

1. Graph activity 在 timeout/cancel 后没有可靠的 durable terminal result，可能在恢复时重复执行。
2. 动态 `TaskPlan` 的 replacement、retry 和 gate admission 语义没有在 `PLAN -> EXECUTE -> VERIFY` 全链路保持一致。
3. Tool、MCP、skill、memory 和 side-effect 的授权输入存在被调用方或 worker 自行声明、旁路或重复执行的路径。
4. Redaction、artifact checksum、schema path、event projection 和测试 oracle 在边界处不能保持数据完整性或诊断准确性。

本 PRD 不把所有审计条目打包成一个无界重构。第一阶段先关闭唯一 P0 和可影响控制权/数据完整性的 P1；生产未接线的公共 API、测试适配器和 legacy surface 进入 P2 队列，必须有 owner、触发条件和验收标准，但不阻塞当前生产发布，除非接线发生变化。

## 3. 现状与证据分级

### 3.1 审计结果

用户提供的审计汇总包含 27 条 finding：标题状态为 25 条 `confirmed`、2 条 `disputed`。`VOTE[refute] confirmed` 表示根因仍被确认，但触发条件、生产可达性或严重度被收窄；不能把它解释为“问题不存在”。

### 3.2 证据分级

后续实施和发布必须区分以下三种证据：

| 级别 | 含义 | 发布用途 |
| --- | --- | --- |
| `runtime_reproduced` | 在真实运行调用链或真实 composition 中复现 | 可作为生产 blocker 的关闭证据 |
| `contract_reproduced` | 在 framework 公共 API、reference adapter 或 fake provider 中复现，但当前没有生产调用方 | 关闭框架契约缺陷；不能声称线上事故已修复 |
| `coverage_gap` | 代码行为未必错误，但测试无法证明约束 | 需要补 oracle 或行为测试，不得改写为运行时缺陷 |

实现者必须在 evidence 中记录 `HEAD`、worktree 差异、调用方搜索结果、复现命令、测试结果和未验证假设。通过测试不替代真实运行路径证据。

## 4. 目标与非目标

### 4.1 目标

- 任何已开始的 Graph activity 在 timeout、cancel、worker failure 或 termination uncertainty 下都能生成可持久化、可回放、带 identity 的 terminal result。
- `TaskPlan` replacement、retry、gate registration 和 aggregation 在 live runner、durable store、replay、recovery 中使用同一判定。
- `ToolPolicy` 是 tool approval 的最终确定性输入；MCP 远端 metadata 不能把外部写操作降级为 read-only。
- Redaction 只移除真实 secret，不破坏普通文本和类型化数值；跨 tool、LLM、agent、memory、transcript 入口行为一致。
- Skill promotion 和 Memory mutation 只能消费 Harness 解析过的外部证据，并再次执行 policy 校验。
- 为 P2 生命周期、资源释放、诊断和测试 oracle 建立有 owner 的后续切片，避免审计结论在下一次接线时重新出现。
- 保留现有运行路径：`source collection -> evidence -> agent analysis -> report -> quality gate -> artifacts/storage`，不让 LLM 获得 routing、quality、authorization、memory write 或 publication authority。

### 4.2 非目标

- 不重写 Graph scheduler、workflow compiler 或 `PLAN -> EXECUTE -> VERIFY` 状态机。
- 不把当前同步、bounded 的 Research dynamic TaskPlan 改造成分布式 DAG engine。
- 不在没有真实 provider、approval record、evaluation cases 或 deployment capability 的情况下用 fake 结果宣称 production-ready。
- 不在本 change 内同时实现所有 P2 legacy API；P2 必须按生产可达性和风险排序进入后续 change。
- 不引入跨服务 distributed transaction 或无法证明的 exactly-once；对外部副作用使用 durable decision、idempotency、outcome 和 indeterminate/quarantine 语义。
- 不修改与本 PRD 无关的 frontend、业务模型、Source policy 或历史 OpenSpec 归档结果。

## 5. 优先级与范围

### 5.1 本修复计划必须关闭的 P0/P1

| ID | 严重度 | 主要位置 | 修复目标 | 生产可达性 |
| --- | --- | --- | --- | --- |
| `R0-ACTIVITY-TERMINAL` | P0 | `framework/harness/runtime/graph_dispatcher.py:100-108`、`activity_executor.py:318-401`、`framework/shared/attempts.py:1529-1549` | timeout/cancel/indeterminate 有 durable result，未确认终止时禁止自动重派发 | 真实 Graph dispatcher 可达 |
| `R1-TASK-REPLACEMENT` | P1 | `framework/harness/task_plan/patches.py`、`stage.py:227-231`、store/replay/recovery | replacement 后旧 FAILED task 明确退出 active plan，required role 可恢复，依赖可重指 | framework API；动态 TaskPlan runner 可达 |
| `R2-TASK-RETRY` | P1 | `framework/harness/task_plan/stage.py:275-292` | 只对 `retryable_reason_codes` 允许的错误重试，gate failure 不得伪装成 worker failure | 动态 TaskPlan runner 可达 |
| `R3-TOOL-APPROVAL` | P1 | `framework/tool/runtime/executor.py:1200-1205,1529-1536`、MCP adapter | `ToolPolicy.require_approval_for` 必须生效；MCP metadata 默认不可信 | 公共 API/MCP opt-in 可达 |
| `R4-REDACTION-INTEGRITY` | P1 | `framework/shared/redaction.py:23-25,76-82` | secret pattern 有边界；普通文本不被改写；transcript 不因误报被拒绝 | tool/memory/transcript/LLM 共享入口可达 |
| `R5-SKILL-APPROVAL` | P1 | `framework/harness/skills/evolution/gates.py:108-118` | approval ref 只能来自 Harness resolver，候选 metadata 不得提供授权 | 当前为 framework/fake；真实接线前 blocker |
| `R6-MEMORY-POLICY` | P1 | `framework/memory/runtime/promotion.py`、`runtime.py:219-257`、`writer.py:166-168` | `promote/PROMOTE/invalidate/forget` 全部执行同一 MemoryPolicy | 公共 MemoryRuntime 可达；当前业务接线有限 |

### 5.2 P2 收口队列

以下条目确认存在或确认测试守卫不足，但当前生产调用链有限；不得丢失，按后续切片交付：

| 队列 | 条目 | 处理要求 |
| --- | --- | --- |
| `P2-TASK` | gate registry 自反检查、InMemory retry result 取早期 FAILED | 补真实 registry/store contract test；生产拒绝 reference store 的事实写入 evidence |
| `P2-SIDE-EFFECT` | serial side-effect crash window 可能重复执行 | 引入 `indeterminate`/`reconcile` 或明确幂等能力门禁；保留 bounded attempt limit |
| `P2-LIFECYCLE` | `approval_required` executable node、queue lease fencing、ChildAgentSupervisor 持锁 cancel、wait binding retention | 补公开恢复语义、fence token、锁外 cancel、terminal binding release |
| `P2-LLM` | OpenAI client 不读取 deadline/cancel、`max_tokens` 被 redaction、compressor 丢 system | 以 AttemptContext、typed field whitelist 和 system-preserving compression 修复 |
| `P2-STORAGE` | artifact checksum 未在 resolver/replay 校验、skill schema path 可越界 | resolver 强制 checksum；schema path 必须 containment；hash 覆盖声明文件 |
| `P2-EVENT` | projection sink 失败与规范 commit 混淆、durable event recovery 裸吞 corruption | 分离 canonical append 与 observation sink；保留原异常类别和 repair signal |
| `P2-TEST-ORACLE` | GraphMemoryPort 恒真测试、runtime raw payload 测试、caller inventory 路径白名单、side-effect boundary 行为覆盖不足 | 改为 AST/行为级、精确异常路径和全 production roots 扫描 |
| `P2-EVAL` | skill evaluator/fake 以请求或默认值伪造分数 | 无真实 cases 时拒绝；生产端只消费真实 evaluation record |

### 5.3 争议条目

- `HarnessControlPlane.resume_after_approval` 保留为 P2 hardening：当前要求调用方已经持有等价 in-process Harness 能力，未发现不可信生产入口；如未来暴露 HTTP/API，必须升为 P1 并复用 verified approval service。
- `tests/architecture/test_harness_side_effect_port_boundary.py` 不作为运行时 defect；记录为 coverage gap，只补缺失的行为回归测试。

## 6. 功能需求

### FR-01：Activity terminal result 与 cancellation uncertainty

1. activity 一旦开始，任何 `TIMED_OUT`、`CANCELLED`、`FAILED` 或 `INDETERMINATE` outcome 都必须生成结构化 worker evidence，至少包含 `run_id`、`graph_id`、`node_id`、`activity_id`、`attempt_id`、`attempt_state`、`reason_code`、`termination_confirmed` 和 `indeterminate`。
2. `_ResultCommitter` 不得因为没有成功 candidate 而拒绝一个已经开始且有终态的 failure result；失败 evidence 必须进入 canonical durable event/replay 记录。
3. cooperative cancel 必须映射为 `CANCELLED`；timeout 与 termination unconfirmed 必须保持可区分。
4. `termination_confirmed=False` 时，recovery/reconcile 不得再次物理 dispatch；只有线程/进程终止得到确认，或 operator 通过显式 repair action 处理后，才允许下一次尝试。
5. 所有 failure commit 路径必须保证 `mark_activity_dispatched`、result event 和 projection 的顺序可恢复；异常不能留下“已运行但无结果”的裸 activity。
6. 此处不允许回退到宿主进程执行，也不允许通过增加 retry 次数掩盖 termination uncertainty。

### FR-02：TaskPlan replacement 语义

1. `ADD_REPLACEMENT_TASK` 生成的 v2 plan 必须明确记录旧 task 与 replacement task 的关系；旧 task 不得继续作为 active producer 或阻塞条件。
2. 对 required output role，replacement 必须提供同一合法 role；对依赖旧 task 的下游定义，patch 必须同时提供合法的 dependency rewire，或在 validation 阶段明确拒绝。
3. projection、aggregation、replay reducer 和 recovery 对 replaced task 使用同一终态判定；不能只在 patch validator 中把 FAILED 忽略。
4. `stage.py` 只有在存在非终态且不可推进的 task 时才返回 `task_plan_task_blocked`；被替换、被显式 skip 或已完成的 task 不得触发该错误。
5. replacement 场景成功后必须写入 `STAGE_OUTPUT_AGGREGATED` 和 `TASK_PLAN_VERIFIED`，并且 `output_refs_by_role` 来自 replacement task。

### FR-03：TaskPlan retry 和 gate admission

1. `retryable_reason_codes` 是执行策略，不是只用于 checksum 的 metadata。
2. `result.error_code` 只有在 `resolved.normalized_retry_policy.retryable_reason_codes` 中时才可生成 `TASK_RETRY_SCHEDULED`。
3. 空列表语义固定为“不可重试”，并在 model、docs、validator、runner、replay、recovery 中一致。
4. 不允许把 `task_gate_failed`、`task_plan_gate_unavailable` 等确定性 acceptance/gate failure 当成 worker retry，除非 policy 显式声明并经过 owner review。
5. PLAN 阶段必须使用实际 gate registry refs；`policy.allowed_gate_refs` 只能表达允许集合，不能冒充已注册集合。未知 gate 必须在任何 worker activity 前 fail closed。
6. live runner、durable recovery 和 replay 对 retry event 的合法性使用同一 policy 判定；当前历史事件兼容策略必须写入 migration evidence。

### FR-04：Tool approval 与 MCP trust boundary

1. executor 的 approval gate 和 trace 必须调用 `ToolPolicy.requires_approval(definition)`，不得只根据 `ToolDefinition` 自报字段判断。
2. `require_approval_for` 的 tool name match 优先于 definition 的 `read_only` 声明；policy 未允许时仍不得执行。
3. MCP server 提供的 `side_effect`、`is_dangerous`、`requires_approval` 属于 untrusted observed metadata。缺省或非法值必须按高风险/需审批处理，或要求 operator-side classification map 后才注册。
4. MCP tool 不能通过自报 `read_only` 绕过 `require_approval_for`、dangerous gate 或 network policy。
5. worker、tool definition 和 remote server 都不能直接写入 `approved` 或等价授权结果；授权由 Harness/approval service 生成并持久化。

### FR-05：Redaction 与 typed data integrity

1. shared secret pattern 必须要求合适的 token boundary 和真实 key 长度；`task-plan-*`、`risk-assessment`、`desk-lamp-holder` 等普通文本必须原样保留。
2. redaction 必须跨 `framework/shared`、`framework/tool`、`framework/llm`、`framework/agent`、`framework/memory` 和 subagent transcript 使用一致规则。
3. `max_tokens`、`max_completion_tokens` 等类型化数值字段不得被替换为字符串；只对 metadata/messages/tools 中的敏感值递归脱敏。
4. transcript 对 secret content 的拒绝必须只针对真实敏感值；普通文本不得触发 `subagent_transcript_secret_content_rejected`。
5. redaction 负例测试必须覆盖完整对象路径、嵌套 mapping、列表、URL/Bearer 和普通领域文本；不得只测试一个真正的 key。

### FR-06：Skill promotion 与 Memory policy

1. `SkillAllowedToolsGate` 不得从 candidate metadata 回退读取 `approval_ref`；候选只能提出 observation，不能提出 Harness approval evidence。
2. 高风险 skill promotion 必须解析 side-effect store 中与 candidate、scope、policy、version 绑定的真实 approval record；sha256 形状检查不是授权证明。
3. 无真实 held-out cases 或 evaluation record 时，skill evaluation 必须拒绝或返回明确 `evaluation_unavailable`，不得使用默认 score/passed。
4. `MemoryRuntime.promote`、`MemoryWriteMode.PROMOTE`、`invalidate/invalidate_many` 和 `forget` 都必须经过统一 `memory_policy_decision` 与 `policy.validate_write`。
5. 目标 scope、kind 和 operation 变更后必须重新校验；默认 `allow_global_write=False` 时，任何间接 promote 到 `GLOBAL` 都必须被拒绝。
6. 普通 business run 不得写 active skill，不得通过 memory record 或 candidate metadata 获得 promotion authority。

### FR-07：Side-effect crash recovery

1. serial handler 在 `commit` 已返回但 `put_outcome` 未完成时，状态必须标为 indeterminate，而不是默认重复执行。
2. 只有存在 stable idempotency contract 或可验证 `reconcile` handler 时，recovery 才能按相同 effect identity 重试；否则 quarantine 并等待 operator/repair service。
3. `effect_attempt_limit`、idempotency key、authorization decision、outcome checksum 和 handler ref 必须一起持久化并可回放。
4. 已有 durable outcome 的 effect recovery 不得再次调用 handler；replay 永远不调用 worker 或 effect handler。

### FR-08：P2 生命周期、存储、事件和测试收口

P2 不改变本阶段的 P0/P1 发布顺序，但每一项必须登记 owner、触发条件、是否生产接线、目标 change 和回归测试。至少包括：

- in-memory queue 的 lease token/fencing 和 stale ack/fail 行为；
- ChildAgentSupervisor 锁外 cancellation/join 和 capacity release；
- terminal wait binding/control plane cache 的 release/eviction；
- LLM client 的 AttemptContext deadline/cancel/retry sleep；
- artifact resolver/replay 的 reference checksum verification；
- skill schema path containment 和 package hash coverage；
- context runtime canonical append 与 projection sink 的错误分离；
- durable event recovery 保留 corruption/unavailability error class；
- system message-preserving context compression；
- 精确化 runtime event、GraphMemoryPort 和 production caller inventory 测试 oracle。

## 7. 关键运行合同

### 7.1 失败 activity 状态流

```text
STARTED
  -> SUCCEEDED
  -> FAILED
  -> CANCELLED
  -> TIMED_OUT
  -> INDETERMINATE (termination_confirmed = false)
```

`INDETERMINATE` 是安全终态，不是普通 retry hint。它必须阻断自动物理重派发，并保留 repair/reconcile 所需的完整 identity。

### 7.2 TaskPlan replacement 状态流

```text
FAILED(A)
  -> PlanPatch(base_version = v1, ADD_REPLACEMENT_TASK A -> A2)
  -> REPLACED(A) + PENDING(A2)
  -> SUCCEEDED(A2)
  -> AGGREGATED -> VERIFIED
```

旧 plan 保持不可变；新 plan 必须通过 `base_plan_version`、policy checksum、capability、budget、gate registry 和 dependency validation。旧 task 的历史结果可供诊断和 replay，但不能再作为 active producer。

### 7.3 授权边界

```text
worker candidate/observation
        |
        v
deterministic Harness validation + policy + gate + approval resolver
        |
        v
durable authorization decision
        |
        v
effect handler / publication / promotion
        |
        v
durable outcome + read-back verification
```

LLM/worker 不能跳过中间两步；Tool/MCP/skill/memory 不能把自身 metadata 当成授权事实。

## 8. 用户与运维场景

### 场景 A：Graph activity timeout

一个 LLM 或 external tool 在 activity deadline 后仍未返回。Harness 记录 `TIMED_OUT` 或 `INDETERMINATE`，写入 durable event，停止自动重派发，并让 operator 能通过 run/activity/attempt identity 查到未确认终止原因。

### 场景 B：TaskPlan helper replacement

`helper` 重试耗尽后，调用方提交带 `base_plan_version` 的 replacement patch。`helper` 在新 projection 中被标记为 replaced，`helper-replacement` 成功后聚合完成；下游依赖已重指时，run 返回 `SUCCEEDED` 并写入 `TASK_PLAN_VERIFIED`。

### 场景 C：Gate failure

worker 返回 candidate，但 deterministic gate 返回 `task_gate_failed`。如果 retry policy 未声明该 reason code，Harness 不得生成 `TASK_RETRY_SCHEDULED`，而应进入受控 failure/halt；worker 只被调用一次。

### 场景 D：MCP remote write

MCP server 的 tool metadata 缺失或自报 `read_only`，但实际执行 external write。Harness 按不可信 metadata 处理，在调用前返回 `APPROVAL_REQUIRED` 或 typed blocked，不能调用 remote client。

### 场景 E：Skill/memory authorization

候选 metadata 携带任意 sha256 approval ref，或调用方先写 SESSION 再 promote GLOBAL。Harness 必须拒绝并记录 policy/approval reason code，不能改变 active skill 或 global memory。

### 场景 F：Side-effect crash

handler 已完成外部 commit，但 outcome 落盘失败。恢复时 Harness 看到未确认 attempt，按 handler capability 决定 reconcile 或 quarantine，不盲目执行第二次。

## 9. 验收标准

### 9.1 P0/P1 质量门

| ID | 验收条件 | 必要证据 |
| --- | --- | --- |
| `AC-01` | hanging worker 经过真实 dispatcher/committer 后产生 TIMEOUT/INDETERMINATE durable result，不抛 `graph_physical_result_worker_evidence_missing` | dispatcher integration test + event/projection assertion |
| `AC-02` | `termination_confirmed=False` 时 `reconcile()` 不再次 dispatch；确认终止后才可进入受控后续尝试 | timeout/cancel/recovery test |
| `AC-03` | replacement 后旧 FAILED task 不阻塞，required role 由 replacement 提供，写入 `STAGE_OUTPUT_AGGREGATED` 和 `TASK_PLAN_VERIFIED` | runner-level test + durable replay checksum |
| `AC-04` | `retryable_reason_codes=('transport',)` 时 `task_gate_failed` 不重试；`transport` 会按 max attempts 重试 | runner matrix test |
| `AC-05` | policy 与 gate registry 不一致时在 worker dispatch 前返回 typed denial | PLAN preflight test |
| `AC-06` | `require_approval_for` 对 read-only definition 仍返回 `APPROVAL_REQUIRED`；缺失/不可信 MCP metadata 不得执行 | ToolExecutor/MCP behavior tests |
| `AC-07` | redaction 负例保持原文，真实 secret 被替换；`max_tokens` 保持整数；transcript 不误拒绝 | cross-entry redaction tests |
| `AC-08` | candidate metadata approval ref 不影响 skill promotion；无真实 eval cases 不得返回 passed | skill evolution adversarial tests |
| `AC-09` | MemoryPolicy 禁止 global write 时 promote/PROMOTE/invalidate/forget 全部拒绝越权操作 | MemoryRuntime policy matrix |
| `AC-10` | serial side-effect crash window 不产生未经 capability/reconcile 许可的第二次 commit | side-effect recovery integration test |

### 9.2 P2 交付门

- 每个 P2 条目有 issue/change owner、生产可达性和目标日期。
- 测试 oracle 缺口已转为行为级或精确 AST/异常断言；不以“测试通过”作为运行时修复证明。
- P2 代码切片完成后运行其 owner change 的 focused tests、compile 和 strict OpenSpec validation。

### 9.3 全局验证

本 change 进入 release candidate 前必须执行并保存输出：

```powershell
.\.venv\Scripts\python.exe -m scripts.dev compile
.\.venv\Scripts\python.exe -m scripts.dev smoke
openspec validate harness-runtime-execution-safety --strict
openspec validate framework-runtime-audit-repair --strict
openspec validate --all --strict
```

如果现有 `harness-runtime-execution-safety` 的 5.1-5.4 仍未完成，不能将本 PRD 标记为 P0 完成；必须记录未完成项和环境 blocker。

## 10. 实施切片与责任边界

| Phase | 内容 | 主要 owner | Exit criteria |
| --- | --- | --- | --- |
| 0 | 锁定 HEAD/worktree/OpenSpec；为 P0/P1 建立最小 runner/integration repro | Harness maintainers | 每个 finding 有可重复失败测试和调用方分类 |
| 1 | 关闭 `R0-ACTIVITY-TERMINAL`；补 durable failure event、indeterminate recovery、防重派发 | `harness-runtime-execution-safety` | `AC-01`、`AC-02`、OpenSpec 5.1-5.4 |
| 2 | 关闭 `R1-TASK-REPLACEMENT`、`R2-TASK-RETRY`；统一 store/projection/replay/recovery | TaskPlan owner | `AC-03`、`AC-04`、`AC-05` |
| 3 | 关闭 `R3-TOOL-APPROVAL`、`R4-REDACTION-INTEGRITY` | Tool/LLM runtime owner | `AC-06`、`AC-07` |
| 4 | 关闭 `R5-SKILL-APPROVAL`、`R6-MEMORY-POLICY`；确认无生产 fake promotion/eval | Skill/Memory owner | `AC-08`、`AC-09` |
| 5 | 批量处理 P2 lifecycle/storage/event/test-oracle；补 release evidence | 各 owner | P2 queue 有明确完成/延期状态，`smoke` 和 strict validation 通过 |

责任边界必须保持：

- interface/application service 调用 application port，不直接访问 executor/store。
- Harness 决定 routing、gate、retry、authorization、memory write 和 publication；worker 只产生 candidate/observation。
- MCP inbound server 与 ToolRuntime outbound adapter 不合并职责。
- `framework/harness/task_plan` 不依赖 legacy `backend/boards/paper_radar`、`interfaces` 或 `infrastructure` 作为业务捷径。
- P0 execution safety 复用 `harness-runtime-execution-safety` 的 contract，不复制第二套 timeout/termination authority。

## 11. 发布、灰度与回滚

1. P0 failure result 和防重派发默认启用；不提供“旧逻辑 fallback”来绕过 durable evidence。
2. Tool/MCP policy 修复先在 deny/approval shadow metrics 中观察，再切换执行门；远端 metadata 缺失按 fail closed 处理。
3. Skill evolution 只有在真实 approval resolver、evaluation cases 和 release authority 都存在时才允许 production enable；否则保持 disabled/blocked。
4. Memory promote/invalidate/forget 修复可先以拒绝越权为默认，保留合法 scope/kind 的正常路径。
5. 回滚只能回到仍能读取新旧 durable event/result 的版本；不删除已有事件、candidate、quarantine 或 side-effect outcome。
6. 任何核心 gate 失败时停止新任务或进入 quarantine；不得自动降级到宿主进程、无审批工具、候选自报分数或未经验证的 memory/skill 写入。

## 12. 可观测性与运维指标

至少记录以下 stable reason code/指标，并按 run/activity/attempt/tenant scope 关联：

- `graph_activity_timeout`、`graph_activity_cancelled`、`graph_activity_indeterminate`；
- `graph_physical_result_worker_evidence_missing` 的发生次数必须在修复后为零；
- prevented redispatch count、unconfirmed termination count、manual reconciliation count；
- `task_plan_retry_not_allowed`、`task_plan_task_blocked`、replacement success/failure；
- approval required/blocked、MCP metadata missing、policy mismatch；
- redaction false-positive regression cases、transcript rejection reason；
- skill approval resolver failure、memory policy denial、side-effect indeterminate/quarantine；
- live wait binding count、dispatcher event map size、per-run control-plane retention。

日志和 metrics 只写 bounded refs/checksums，不写 raw prompt、secret、完整 tool payload、文件内容或 approval evidence body。

## 13. 依赖与风险

| 依赖/风险 | 处理方式 |
| --- | --- |
| `harness-runtime-execution-safety` 仍有未完成 release qualification | 复用其 contract；单独记录 5.1-5.4，不用本 PRD 伪造 deployment evidence |
| TaskPlan replacement 需要改变 projection/replay 语义 | 增加 schema/version 或显式 replaced disposition；保持旧 plan immutable，先做 dual-read |
| retry policy 改变历史行为 | 只对新合法事件执行新规则；历史非法 retry event 在 replay/recovery 中报告诊断，不静默重写 |
| MCP 远端风险 metadata 不可信 | 缺失即高风险/需审批；operator classification 是唯一降级来源 |
| shared redactor 改动会改变 checksum/trace | 先补 golden vectors 和迁移说明；不要回写历史原始 payload |
| 当前 skill/memory/Artifact API 没有生产调用方 | 以 contract-level tests 关闭问题，并在 caller inventory 中记录“未接线”；接线前必须重新评估严重度 |
| side-effect exactly-once 不可证明 | 使用 bounded at-least-once + idempotency/reconcile + indeterminate quarantine，禁止隐式重复 |

## 14. Definition of Done

- P0/P1 表中的 `R0` 至 `R6` 每项都有代码 owner、测试 owner、稳定 reason code 和关闭证据。
- P0 timeout/cancel 场景通过真实 dispatcher/committer/recovery 路径验证，不只使用接受 `worker_result=None` 的 test double。
- TaskPlan replacement/retry/gate 场景通过 runner-level 测试，且 durable store、replay、recovery 的结果一致。
- Tool/MCP approval、redaction、skill approval 和 memory policy 均有 adversarial negative test；worker/remote metadata 不能产生授权。
- P2 队列中的每个条目都有明确的 `completed`、`deferred` 或 `blocked` 状态和理由；未接线条目没有被写成线上故障。
- `.\.venv\Scripts\python.exe -m scripts.dev compile`、`.\.venv\Scripts\python.exe -m scripts.dev smoke`、相关 strict OpenSpec validation 全部通过，或将真实 blocker 记录在 evidence 中。
- 未引入 compatibility layer、宿主进程安全降级、伪造 provider/evaluation/approval 或新的跨层 authority。
- 变更提交保持 path-scoped，不能覆盖用户已有的无关 worktree 修改。
