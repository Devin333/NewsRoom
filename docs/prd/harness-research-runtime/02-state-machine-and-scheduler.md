# 阶段 2：Harness 状态机与调度器

## 阶段目标

实现 Harness Control Plane 的状态机、调度器、显式 routing 和 retry。阶段 2 的重点是证明：流程推进由 Harness 决定，不由 LLM worker 决定。

## 新增或修改目录

```text
framework/harness/control_plane/
  harness.py
  scheduler.py
  transitions.py
  policy.py
  routing.py
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

## 状态转换要求

必须集中在状态机里做转换，不允许散落在 worker 或业务层。

推荐状态：

```text
created -> running
running -> waiting_approval
running -> succeeded
running -> failed
running -> blocked
running -> cancelled
waiting_approval -> running
```

step 状态：

```text
pending -> running
running -> succeeded
running -> failed
running -> retrying
retrying -> running
running -> waiting_approval
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
- illegal transition 抛错。
- fake LLM worker 输出 `{"next_step": "publish"}` 时，scheduler 不采纳。
- quality gate failed 后按 policy 返工或失败。

## 验收命令

```powershell
python -m scripts.dev compile
python -m pytest tests/framework/harness -q
openspec validate harness-research-runtime --strict
```

## 完成标准

- Harness 能驱动一个 fake workflow 从 created 到 succeeded。
- LLM worker 输出不能影响 routing。
- retry 和 fail 行为可测试。
- 状态转换集中且非法转换有保护。
- 不接旧业务，不做 UI。
- 完成后提交。

## 可复制给 Codex 的任务提示

```text
请执行 docs/prd/harness-research-runtime/02-state-machine-and-scheduler.md。
要求：
1. 实现 framework/harness 的 HarnessControlPlane、HarnessScheduler、状态转换、routing rule 和 retry policy。
2. 不接入旧 AgentLoop 或旧 WorkflowExecutor。
3. 证明 LLM worker 输出中的 next_step 等字段不会影响流程路由。
4. 添加状态机、调度、retry、非法转换、LLM 不能路由的测试。
5. 运行 python -m scripts.dev compile、python -m pytest tests/framework/harness -q、openspec validate harness-research-runtime --strict。
6. 修改完成后提交。
全部回复和问题用中文。
```
