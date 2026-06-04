# 阶段 8：旧框架清理

## 阶段目标

清理旧框架层。保留服务新 Harness 的通用资产；删除无用旧控制流、重复抽象、业务污染和旧 eval harness。阶段 8 不删除旧业务层主体，旧业务和旧测试在阶段 9 处理。

## 审计复核规则

阶段 8 执行前必须重新验证阶段 0 的 `audit-inventory.md`：

- 每个 `delete` 候选都要重新用 `rg` 检查当前引用。
- 如果阶段 1-7 的实现改变了依赖关系，必须更新 `audit-inventory.md` 的 category、reason、replacement、deletion_phase。
- 如果原 audit 把仍有价值的通用能力误标为 delete，改为 keep 或 adapt，并补充理由。
- 如果发现新 Harness 已经完全替代某个旧控制流，但 audit 未标记，允许补充 delete 候选。
- 不允许因为 audit 写了 delete 就无条件删除；删除动作以执行时复核结果为准。

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

`framework/skills` 默认作为保留资产，后续用于：

- skill package scanning/loading。
- skill manifest 和 metadata。
- input/output schema validation。
- skill runtime executor。
- skill quality gates。
- versioned skill registry adapter。
- skills evolution 的 candidate static validation 和 eval runner。

如果发现 `framework/skills` 里的兼容模块只转发旧路径，可以在确认所有新代码都使用新包路径后删除或保留为短期 deprecated export；不能删除真实 package/runtime/validation/quality 能力。

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

Skills 自进化相关代码还必须避免：

```text
auto_promote
self_modify_production_skill
llm_decides_promotion
disable_quality_gate
skip_eval
```

如果这些词只出现在测试里用于验证禁止行为，可以保留。

## 架构测试

新增或更新：

```text
tests/architecture/test_framework_harness_boundary.py
tests/architecture/test_framework_no_business_pollution.py
tests/architecture/test_framework_exports_after_cleanup.py
tests/architecture/test_skill_evolution_boundary.py
```

必须检查：

- `framework/harness` 不 import business/interfaces/infrastructure。
- framework 生产代码不包含旧业务污染模块。
- 删除旧 harness 后公共导出不破。
- skill evolution 不 import business/interfaces/infrastructure。
- production code 不允许出现自动晋升、跳过 eval、LLM 决定发布等 bypass 行为。
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
- Skills package/runtime/validation/quality 能力仍可被 Harness skill evolution 使用。
- Research 测试仍通过。
- 无旧 `framework/agent/harness` 公共依赖。
- 删除的框架测试都有废弃理由。
- 完成后提交。

## 可复制给 Codex 的任务提示

```text
请执行 docs/prd/harness-research-runtime/08-framework-cleanup.md。
要求：
1. 先复核阶段 0 audit-inventory.md；如果 keep/adapt/delete 结论已过期，更新审计清单后再清理旧 framework。
2. 保留 llm/tool/memory/skills/artifacts/events/workers/scoring/governance/shared 等可用资产。
3. 保留 framework/skills 的 package、runtime、validation、quality 能力，作为 Harness skill evolution 的底层资产。
4. 删除业务污染、重复抽象、旧 harness eval、被新 Harness 替代且无用的旧控制流。
5. 删除只验证废弃旧框架行为的测试；有价值规则迁移到新 Harness 测试。
6. 添加或更新架构边界测试，确保 framework 不含业务污染，skill evolution 不含 auto promote、skip eval、LLM 决定发布等 bypass。
7. 运行 python -m scripts.dev compile、python -m pytest tests/framework/harness tests/business/research tests/architecture -q、openspec validate harness-research-runtime --strict。
8. 修改完成后提交。
全部回复和问题用中文。
```
