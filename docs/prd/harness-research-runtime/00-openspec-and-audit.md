# 阶段 0：OpenSpec 与架构审计

## 阶段目标

建立 `harness-research-runtime` OpenSpec change，并完成现有 `framework`、`business`、`interfaces`、`tests` 的架构审计。阶段 0 不实现新功能，重点是把边界、删除标准和迁移顺序定死。

## 必须产出

| 产物 | 路径 | 内容 |
| --- | --- | --- |
| OpenSpec proposal | `openspec/changes/harness-research-runtime/proposal.md` | 为什么重建、范围、非目标、风险。 |
| OpenSpec design | `openspec/changes/harness-research-runtime/design.md` | Harness + Research 总体设计、分层、边界、删除策略。 |
| OpenSpec tasks | `openspec/changes/harness-research-runtime/tasks.md` | 阶段 1-9 和阶段 3A 的可勾选任务。 |
| Spec delta | `openspec/changes/harness-research-runtime/specs/.../spec.md` | 至少覆盖 Harness runtime 和 Research runtime 两类需求。 |
| 审计清单 | `docs/prd/harness-research-runtime/audit-inventory.md` | `keep / adapt / delete` 表格和理由。 |

## 审计范围

必须审计这些目录：

```text
framework
business
interfaces
tests
openspec/specs
docs/architecture
```

审计时不要只看文件名，要看引用关系、测试覆盖、是否业务污染、是否和新架构重复。

## 分类标准

### keep

满足以下条件之一可以标记为 `keep`：

- 新 Harness 需要的底层能力。
- Research 业务会直接通过 port 或 adapter 使用。
- 通用框架能力，和具体业务无关。
- 仍有明确公共 API 价值，并且测试能覆盖真实规则。

优先 keep 的候选：

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

### adapt

满足以下条件之一标记为 `adapt`：

- 有可复用能力，但现在承担了过多流程控制。
- 需要降级为 Harness worker、adapter 或 runtime utility。
- 需要拆出纯框架部分，删除业务污染部分。

常见候选：

```text
framework/agent/loop
framework/agent/runtime
framework/agent/subagents
framework/agent/session
framework/workflow
framework/specs
```

### delete

满足以下条件之一标记为 `delete`：

- 不服务新 Harness + Research。
- 只为旧业务、旧接口、旧 UI、旧兼容存在。
- 业务代码污染框架层。
- 新 Harness 已替代其职责。
- 无引用、重复抽象、临时实现或只为旧测试服务。

重点检查候选：

```text
framework/agent/harness
framework/agent/subagents/paper_reader_artifact_reviewer.py
business/boards/paper_radar
business/boards/cross_board
business/boards/project_radar
business/boards/community_pulse
interfaces/services/paper_*.py
interfaces/api/routers/papers.py
tests/business/boards
tests/interfaces/services/test_paper_*.py
tests/interfaces/api/test_papers_*.py
frontend paper UI tests
```

阶段 0 只标记，不大规模删除。删除在阶段 8 和阶段 9 执行。

## 具体执行步骤

1. 用 `rg --files` 列出现有模块。
2. 用 `rg -n "from framework|import framework|from business|import business"` 建引用图。
3. 用 `rg -n "paper_radar|paper_reader|papers|Research|harness|AgentLoop|WorkflowExecutor"` 找旧路径和新目标相关代码。
4. 读取重点模块，不要只靠 grep 判断。
5. 在 `audit-inventory.md` 记录表格：

```text
path | category | reason | replacement | deletion_phase | tests_action
```

6. 建立 OpenSpec change。
7. 运行 `openspec validate harness-research-runtime --strict`。

## OpenSpec 需求要点

必须写入以下 requirement：

- Harness MUST be the only workflow decision maker.
- LLM workers MUST NOT control routing, quality verdicts, memory writes, tool authorization, or publication.
- Skills evolution MUST be Harness-controlled: LLM optimizers MAY propose candidates or patches, but MUST NOT modify active skill packages, decide promotion, skip held-out evals, disable quality gates, or publish production versions.
- Research MUST NOT depend on legacy `business/boards/paper_radar`, `interfaces`, or `infrastructure`.
- Legacy code and tests MUST be deleted when they no longer serve Harness + Research.
- UI MUST be out of scope for this change.

Skill 相关审计必须特别标记：

```text
framework/skills/package
framework/skills/runtime
framework/skills/validation
framework/skills/quality
business/foundation/skills
```

这些默认是 `keep` 或 `adapt` 候选，因为阶段 3A 会复用它们实现 skill candidate 校验、eval replay、versioned registry adapter 和 rollback。

## 测试与验证

阶段 0 没有业务测试要求，但必须运行：

```powershell
openspec validate harness-research-runtime --strict
python -m scripts.dev compile
```

如果 compile 因无关既有问题失败，必须记录在 `audit-inventory.md` 的 `known_preexisting_failures` 区域，不要修改无关代码。

## 完成标准

- `harness-research-runtime` change 存在且 strict validate 通过。
- `audit-inventory.md` 覆盖主要旧框架、旧业务、旧测试。
- 每个 `delete` 候选都有明确理由和计划删除阶段。
- 没有实现新 runtime，不引入半成品代码。
- 完成后提交。

## 可复制给 Codex 的任务提示

```text
请执行 docs/prd/harness-research-runtime/00-openspec-and-audit.md。
要求：
1. 建立 openspec/changes/harness-research-runtime，写 proposal/design/tasks/spec delta，覆盖 Harness、Research 和 skills evolution。
2. 审计 framework、business、interfaces、tests，生成 docs/prd/harness-research-runtime/audit-inventory.md。
3. 按 keep/adapt/delete 标记旧资产，说明理由、替代方案、删除阶段和测试处理方式；framework/skills 需要单独说明哪些能力保留给阶段 3A。
4. 不实现新功能，不做 UI。
5. 运行 openspec validate harness-research-runtime --strict 和 python -m scripts.dev compile。
6. 修改完成后提交。
全部回复和问题用中文。
```
