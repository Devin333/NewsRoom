# 阶段 2：Harness 状态机与调度器

## 阶段目标

实现 Harness Control Plane 的状态机、调度器、显式 routing 和 retry。阶段 2 的重点是证明：流程推进由 Harness 决定，不由 LLM worker 决定。

本阶段必须加入有界 `PLAN -> EXECUTE -> VERIFY` 状态机。每个 step 都要先由 Harness 规划，再执行 worker，最后由纯函数 gate 校验。gate 不通过只能触发受控 replan/retry/repair/halt，不能无限重试。

## 新增或修改目录

```text
framework/harness/control_plane/
  harness.py
  scheduler.py
  transitions.py
  policy.py
  routing.py
  phase.py
  gates.py
```

可根据阶段 1 的实际结构调整文件名，但职责必须清晰。

## 核心对象

### HarnessControlPlane

职责：

- 接收 `HarnessRunSpec`。
- 初始化 `HarnessState`。
- 请求 scheduler 选择下一步。
- 执行状态转换。
- 记录事件。
- 驱动每个 step 的 `PLAN -> EXECUTE -> VERIFY` 相位。
- 维护 `max_turns`、`max_replans`、`max_retries_per_step` 和 worker 调用预算。

阶段 2 可以使用 fake worker registry，不接真实 LLM。

### HarnessScheduler

职责：

- 根据 `HarnessState` 和 `HarnessWorkflowSpec` 选择下一个 step。
- 只读 Harness state、step result、routing rules。
- 不读取 LLM 原始文本来决定下一步。

调度规则：

| 场景 | 决策 |
| --- | --- |
| run created | 进入 entry step。 |
| step pending | 进入 PLAN 相位。 |
| PLAN gate 通过 | 进入 EXECUTE 相位。 |
| PLAN gate 不通过 | replan 或 halt。 |
| EXECUTE 完成 | 进入 VERIFY 相位。 |
| VERIFY gate 通过 | complete step。 |
| VERIFY gate 不通过且 replan 未耗尽 | replan 或 route_to_repair。 |
| VERIFY gate 不通过且 replan 耗尽 | halt 或 fail run。 |
| step succeeded 且无 routing | 进入下一个拓扑 step。 |
| step succeeded 且有 routing | 用显式 rule 决定目标 step。 |
| step failed 且 retry 未耗尽 | retry 当前 step。 |
| step failed 且 retry 耗尽 | fail run 或进入配置的 repair step。 |
| quality gate failed | 按 policy retry、repair 或 fail。 |
| approval required | waiting_approval。 |

### RoutingRule

显式 routing 只能基于结构化字段：

```text
state.inputs.*
state.outputs.*
state.step_status.*
worker_result.status
quality_verdict.passed
quality_verdict.score
```

禁止基于 LLM 自由文本中的 `next step`、`should publish`、`I think done` 等内容。

### RetryPolicy

字段建议：

```text
max_attempts
retry_on_statuses
backoff_seconds
repair_step_id
fail_fast_error_types
```

阶段 2 不需要真实 sleep，可以把 backoff 记录进 decision。

### HarnessTurnBudget

字段建议：

```text
max_turns
max_replans
max_retries_per_step
max_worker_calls
halt_on_budget_exceeded
```

要求：

- 所有 run 必须有预算，缺失时使用安全默认值。
- 每次 PLAN、EXECUTE、VERIFY 都计入 transcript。
- replan 次数超过 `max_replans` 时进入 `halted`。
- turn 次数超过 `max_turns` 时进入 `halted`。
- `halted` 是受控终态，必须带 reason。

### DeterministicGate

位置：`framework/harness/control_plane/gates.py`

职责：

- 用纯函数校验计划和 worker 输出。
- 不调用 LLM、不访问外部服务、不产生 side effect。

第一批 gate：

| Gate | 校验内容 |
| --- | --- |
| `ToolAllowlistGate` | worker 请求的工具必须在 step allowlist 内。 |
| `OutputSchemaGate` | worker output 必须符合 step schema。 |
| `DeduplicationGate` | 同一 run 内不能重复执行相同 plan key 或产生重复 claim/question。 |
| `ScoreRangeGate` | score/rating/confidence 等数值必须在配置范围内，例如 1-5 或 0-1。 |
| `BudgetGate` | replan、retry、turn、worker call 不能超过预算。 |

## 状态转换要求

必须集中在状态机里做转换，不允许散落在 worker 或业务层。

推荐状态：

```text
created -> running
running -> planning
planning -> executing
executing -> verifying
verifying -> replanning
replanning -> planning
verifying -> running
running -> waiting_approval
running -> succeeded
running -> failed
running -> halted
running -> blocked
running -> cancelled
waiting_approval -> running
```

step 状态：

```text
pending -> running
running -> planning
planning -> executing
executing -> verifying
verifying -> succeeded
verifying -> replanning
replanning -> planning
running -> succeeded
running -> failed
running -> retrying
retrying -> running
running -> waiting_approval
running -> halted
```

非法转换必须抛出 Harness 层错误。

## 与旧框架的关系

阶段 2 不要接入旧 `AgentLoop` 或旧 `WorkflowExecutor`。旧模块最多作为参考，不参与新状态机。

原因：

- 旧 loop 里已经有流程控制。
- 新 Harness 必须先建立自己的决策权。
- 后续阶段可以把旧 AgentLoop 降级成 worker adapter。

## 测试要求

新增：

```text
tests/framework/harness/control_plane/test_scheduler.py
tests/framework/harness/control_plane/test_state_transitions.py
tests/framework/harness/control_plane/test_retry_policy.py
tests/framework/harness/control_plane/test_llm_cannot_route.py
```

必须覆盖：

- 线性 workflow 能按顺序执行。
- routing rule 能跳转到指定 step。
- retry 次数耗尽后 fail run。
- max_replans 耗尽后进入 halted。
- max_turns 耗尽后进入 halted。
- illegal transition 抛错。
- fake LLM worker 输出 `{"next_step": "publish"}` 时，scheduler 不采纳。
- 工具白名单 gate 拒绝未授权工具。
- 去重 gate 拒绝重复 plan key。
- 分数 gate 拒绝 1-5 范围外的评分。
- quality gate failed 后按 policy 返工或失败。

## 验收命令

```powershell
python -m scripts.dev compile
python -m pytest tests/framework/harness -q
openspec validate harness-research-runtime --strict
```

## 完成标准

- Harness 能驱动一个 fake workflow 从 created 到 succeeded。
- 每个 step 都经过 PLAN、EXECUTE、VERIFY。
- VERIFY 由纯函数 gate 完成。
- LLM worker 输出不能影响 routing。
- retry 和 fail 行为可测试。
- max_replans / max_turns 能受控 halted，杜绝无限循环。
- 状态转换集中且非法转换有保护。
- 不接旧业务，不做 UI。
- 完成后提交。

## 可复制给 Codex 的任务提示

```text
请执行 docs/prd/harness-research-runtime/02-state-machine-and-scheduler.md。
要求：
1. 实现 framework/harness 的 HarnessControlPlane、HarnessScheduler、状态转换、routing rule、retry policy 和有界 PLAN/EXECUTE/VERIFY 相位模型。
2. 不接入旧 AgentLoop 或旧 WorkflowExecutor。
3. 证明 LLM worker 输出中的 next_step 等字段不会影响流程路由。
4. 添加 ToolAllowlistGate、OutputSchemaGate、DeduplicationGate、ScoreRangeGate、BudgetGate 等纯函数 gate。
5. max_replans、max_turns、max_retries_per_step 超限时必须进入受控 halted，不能无限重试。
6. 添加状态机、调度、retry、replan/halt、非法转换、LLM 不能路由、工具白名单、去重、分数范围测试。
7. 运行 python -m scripts.dev compile、python -m pytest tests/framework/harness -q、openspec validate harness-research-runtime --strict。
8. 修改完成后提交。
全部回复和问题用中文。
```
