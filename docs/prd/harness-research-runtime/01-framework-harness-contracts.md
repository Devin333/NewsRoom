# 阶段 1：框架层 Harness 契约

## 阶段目标

新增 `framework/harness` 包，定义 Harness Control Plane 的核心契约。阶段 1 只做数据模型、接口边界和包结构，不实现完整运行循环。

## 新增目录

```text
framework/harness/
  __init__.py
  control_plane/
    __init__.py
    state.py
    decision.py
    event.py
    trace.py
    errors.py
  workflow/
    __init__.py
    spec.py
    step.py
  workers/
    __init__.py
    result.py
  quality/
    __init__.py
    verdict.py
  runtime/
    __init__.py
    checkpoint.py
```

不要在阶段 1 引入 `business/research`。

## 核心契约

### HarnessRunSpec

位置：`framework/harness/control_plane/state.py`

职责：

- 描述一次 Harness run 的不可变输入。
- 包含 `run_id`、`workflow`、`inputs`、`metadata`。
- 不包含具体业务实现对象。

约束：

- `run_id` 必须非空。
- `inputs` 必须可序列化。
- `workflow` 只能是 Harness workflow spec，不能直接使用旧 `WorkflowSpec` 作为唯一模型。

### HarnessWorkflowSpec

位置：`framework/harness/workflow/spec.py`

职责：

- 描述显式 workflow。
- 包含 step 列表、入口 step、终态策略。
- 支持线性流程和受控 routing。

约束：

- 不允许 workflow 从 LLM output 动态生成。
- routing rule 必须是 Harness 可解释规则。

### HarnessStepSpec

位置：`framework/harness/workflow/step.py`

职责：

- 描述单个 step。
- 包含 `step_id`、`worker_type`、`input_keys`、`output_key`、`retry_policy`、`quality_gate`、`metadata`。

worker type 第一阶段只定义枚举或 literal：

```text
llm
skill
subagent
retrieval
memory
mcp
quality_gate
artifact
script
```

### HarnessState / HarnessStepState

位置：`framework/harness/control_plane/state.py`

职责：

- 保存 run 当前状态。
- 保存每个 step 的状态、重试次数、输出引用、错误。

状态建议：

```text
created
running
waiting_approval
succeeded
failed
cancelled
blocked
```

step 状态建议：

```text
pending
running
retrying
succeeded
failed
skipped
waiting_approval
```

### HarnessDecision

位置：`framework/harness/control_plane/decision.py`

职责：

- Harness 对下一步的唯一决策结果。
- LLM 不允许生成这个对象。

决策类型：

```text
start_step
complete_step
retry_step
route_to_step
wait_for_approval
fail_run
complete_run
cancel_run
block_run
```

### HarnessEvent / HarnessTrace

位置：

```text
framework/harness/control_plane/event.py
framework/harness/control_plane/trace.py
```

职责：

- 记录每次状态变化和 worker 调用摘要。
- 可导出 dict，后续阶段用于 replay。

### HarnessWorkerResult

位置：`framework/harness/workers/result.py`

职责：

- worker 的标准输出。
- 包含 `status`、`output`、`artifacts`、`diagnostics`、`metrics`、`error`。

重点约束：

- 不包含 `next_step`。
- 不包含 `quality_passed` 作为最终判定。
- 不包含 `write_memory=true` 这类直接 side effect 决策。

### HarnessQualityVerdict

位置：`framework/harness/quality/verdict.py`

职责：

- 质量门输出。
- 包含 `passed`、`score`、`issues`、`repair_hints`。

质量门可以建议返工，但最终是否返工由 Harness policy 决定。

## 导出规则

`framework/harness/__init__.py` 只导出稳定公共契约，不要用过宽的 wildcard 暴露内部模块。可以导出：

```text
HarnessRunSpec
HarnessWorkflowSpec
HarnessStepSpec
HarnessState
HarnessStepState
HarnessDecision
HarnessEvent
HarnessTrace
HarnessCheckpoint
HarnessWorkerResult
HarnessQualityVerdict
```

## 禁止事项

- 不 import `business`。
- 不 import `interfaces`。
- 不 import `infrastructure`。
- 不复用旧 `framework.agent.harness` 命名为新实现。
- 不让 `HarnessWorkerResult` 带流程控制字段。
- 不在阶段 1 写完整 executor。

## 测试要求

新增：

```text
tests/framework/harness/test_contracts.py
tests/framework/harness/test_serialization.py
tests/framework/harness/test_worker_result_contract.py
```

必须测试：

- 所有核心对象可 `to_dict`。
- 必填字段校验。
- worker result 不接受或不暴露流程决策字段。
- workflow spec 不能没有入口 step。
- step id 不能重复。

## 验收命令

```powershell
python -m scripts.dev compile
python -m pytest tests/framework/harness -q
openspec validate harness-research-runtime --strict
```

## 完成标准

- `framework/harness` 包存在。
- 核心契约完整、可序列化、可单测。
- 没有业务依赖。
- 没有旧 Harness 兼容逻辑。
- 阶段 1 任务在 OpenSpec tasks 中勾选。
- 完成后提交。

## 可复制给 Codex 的任务提示

```text
请执行 docs/prd/harness-research-runtime/01-framework-harness-contracts.md。
要求：
1. 新增 framework/harness 包和核心契约。
2. 定义 HarnessRunSpec、HarnessWorkflowSpec、HarnessStepSpec、HarnessState、HarnessStepState、HarnessDecision、HarnessEvent、HarnessTrace、HarnessCheckpoint、HarnessWorkerResult、HarnessQualityVerdict。
3. 确保 framework/harness 不依赖 business、interfaces、infrastructure。
4. HarnessWorkerResult 不允许表达 next_step、quality_passed、write_memory 等流程决策。
5. 添加 tests/framework/harness 契约和序列化测试。
6. 运行 python -m scripts.dev compile、python -m pytest tests/framework/harness -q、openspec validate harness-research-runtime --strict。
7. 修改完成后提交。
全部回复和问题用中文。
```
