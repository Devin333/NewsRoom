# 阶段 8：旧框架清理

## 阶段目标

清理旧框架层。保留服务新 Harness 的通用资产；删除无用旧控制流、重复抽象、业务污染和旧 eval harness。阶段 8 不删除旧业务层主体，旧业务和旧测试在阶段 9 处理。

## 保留清单

默认保留，除非审计证明无用：

```text
framework/llm
framework/tool
framework/memory
framework/skills
framework/artifacts
framework/events
framework/workers
framework/scoring
framework/governance
framework/shared
```

这些作为新 Harness 的零件库。

## 改造清单

需要降级为 Harness 下层能力：

```text
framework/agent/loop
framework/agent/runtime
framework/agent/subagents
framework/agent/session
framework/workflow
framework/specs
```

处理方式：

- 如果被新 Harness adapter 使用，保留 adapter 需要的纯框架能力。
- 如果承担旧流程控制且新 Harness 已替代，删除或标记 internal legacy。
- 如果含业务污染，移动到 Research 或删除，不留在 framework。

## 删除候选

重点检查并删除：

```text
framework/agent/harness
framework/agent/subagents/paper_reader_artifact_reviewer.py
framework/workflow/runners/agent_loop.py 如果不再被新路径使用
framework/workflow/runtime 中被 Harness 完全替代且无其他保留理由的旧控制流
```

删除前必须：

1. 用 `rg` 确认引用。
2. 如果只有旧测试引用，判断测试是否废弃。
3. 如果有真实规则，迁移到新 Harness 测试。
4. 更新 `framework/__init__.py` 和 package export。

## 业务污染识别

框架层不允许出现具体业务词：

```text
paper
paper_reader
paper_radar
daily_intelligence
project_radar
community_pulse
newsroom business board
```

例外：

- 测试 fixture 中为了说明用途可以出现，但不应在 framework 生产代码中出现。

## 架构测试

新增或更新：

```text
tests/architecture/test_framework_harness_boundary.py
tests/architecture/test_framework_no_business_pollution.py
tests/architecture/test_framework_exports_after_cleanup.py
```

必须检查：

- `framework/harness` 不 import business/interfaces/infrastructure。
- framework 生产代码不包含旧业务污染模块。
- 删除旧 harness 后公共导出不破。
- Research 仍可运行阶段 6/7 测试。

## 删除测试标准

旧框架测试分三类：

| 类型 | 处理 |
| --- | --- |
| 验证通用框架能力 | 保留或迁移到新路径。 |
| 验证旧 AgentLoop/Workflow 但仍作为 adapter 需要 | 保留并改名说明 legacy adapter。 |
| 只验证废弃旧控制流 | 删除。 |

删除测试前必须确保不是为了掩盖失败，而是因为对应行为已在 OpenSpec 中废弃。

## 验收命令

```powershell
python -m scripts.dev compile
python -m pytest tests/framework/harness tests/business/research tests/architecture -q
openspec validate harness-research-runtime --strict
```

## 完成标准

- 无业务污染 framework 代码。
- 新 Harness 测试仍通过。
- Research 测试仍通过。
- 无旧 `framework/agent/harness` 公共依赖。
- 删除的框架测试都有废弃理由。
- 完成后提交。

## 可复制给 Codex 的任务提示

```text
请执行 docs/prd/harness-research-runtime/08-framework-cleanup.md。
要求：
1. 根据阶段 0 audit-inventory.md 清理旧 framework。
2. 保留 llm/tool/memory/skills/artifacts/events/workers/scoring/governance/shared 等可用资产。
3. 删除业务污染、重复抽象、旧 harness eval、被新 Harness 替代且无用的旧控制流。
4. 删除只验证废弃旧框架行为的测试；有价值规则迁移到新 Harness 测试。
5. 添加或更新架构边界测试，确保 framework 不含业务污染。
6. 运行 python -m scripts.dev compile、python -m pytest tests/framework/harness tests/business/research tests/architecture -q、openspec validate harness-research-runtime --strict。
7. 修改完成后提交。
全部回复和问题用中文。
```
