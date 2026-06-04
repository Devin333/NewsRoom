# Harness Research Runtime PRD Pack

本文档包用于分阶段喂给 Codex，目标是重建 NewsRoom 架构：先做框架层 `Harness Control Plane`，再做业务层 `Research`，暂不做 UI，并在最后删除不再服务新架构的旧代码和旧测试。

## 总目标

重建项目架构，只保留有用资产，删除无用旧代码和旧测试。先做框架层 Harness Control Plane，再做业务层 Research。UI 暂时不做，旧业务层不兼容、不迁移、不适配。

## 核心原则

| 原则 | 要求 |
| --- | --- |
| Harness 控制流程 | Harness 是唯一流程决策者，负责状态推进、路由、重试、质量门、审批、记忆写入和 artifact 发布。 |
| 有界相位状态机 | 每个 step 必须按 `PLAN -> EXECUTE -> VERIFY` 推进；VERIFY 由纯函数 gate 完成，不通过只能受控 replan/retry/halt。 |
| LLM 只做 worker | LLM 只生成候选结构化内容，不决定下一步，不直接写记忆，不直接调用高风险工具，不判定质量通过。 |
| Skills 可进化但受控 | LLM 只能生成 skill candidate 或 patch；Harness 负责经验选择、静态校验、离线 eval、晋升、发布和回滚。 |
| 业务自进化先入记忆 | Reader 修复、论文解析等业务问题先写 episodic/procedural memory；只有稳定策略才进入 skill evolution。 |
| 业务层表达业务 | `business/research` 只表达 Research 领域模型、业务规则、用例和 workflow spec。 |
| Research 不依赖旧代码 | 新 Research 不依赖 `business/boards/paper_radar`、旧 paper API、旧 reader payload 或旧兼容 adapter。 |
| 保留有用资产 | 旧框架层中可复用的 LLM、Tool、Memory、Skills、Artifacts、Events、Workers、Governance 等资产保留。 |
| 删除无用资产 | 不服务新 Harness + Research 的旧业务、旧测试、旧兼容、旧控制流、业务污染框架代码都要删除。 |
| UI 不做 | 本轮只做框架、业务和后端接口，不修改 UI，不做前端迁移。 |

## PLAN / EXECUTE / VERIFY 执行模型

Harness 的每个 step 都必须拆成三个相位：

| 相位 | 职责 | 禁止事项 |
| --- | --- | --- |
| PLAN | 由 Harness 根据 workflow spec、state、policy 和 gate 结果选择本轮执行计划。 | 不允许让 LLM 直接决定计划。 |
| EXECUTE | 调用 LLM、Skill、Retrieval、Memory、SubAgent、MCP 或 Artifact worker 执行受控任务。 | worker 不允许写入最终流程决策。 |
| VERIFY | 用纯函数 gate 校验 worker result、工具白名单、输出 schema、去重、分数范围、证据覆盖和预算。 | 不允许用 LLM 自评替代 gate。 |

VERIFY 不通过时，Harness 只能做显式决策：

```text
replan
retry
route_to_repair
wait_for_approval
halted
failed
```

每个 run 必须有有界预算：

```text
max_turns
max_replans
max_retries_per_step
max_worker_calls
```

超过预算必须进入受控 `halted`，不能继续无限重试。每次相位转移都必须写入 transcript/event log，后续可以 replay 和复盘。

## 阶段文档

| 阶段 | 文件 | 目标 |
| --- | --- | --- |
| 0 | [00-openspec-and-audit.md](00-openspec-and-audit.md) | 建立 OpenSpec change，审计现有代码和测试，形成 keep/adapt/delete 清单。 |
| 1 | [01-framework-harness-contracts.md](01-framework-harness-contracts.md) | 新增 `framework/harness` 核心契约和包结构。 |
| 2 | [02-state-machine-and-scheduler.md](02-state-machine-and-scheduler.md) | 实现 Harness 状态机、显式调度器、路由和重试策略。 |
| 3 | [03-seven-layer-ports.md](03-seven-layer-ports.md) | 建立七层可替换端口和 fake implementation。 |
| 3A | [03a-skill-evolution.md](03a-skill-evolution.md) | 在 Harness 控制下建立 skills 自进化生命周期、候选仓、eval、晋升和回滚。 |
| 4 | [04-trace-checkpoint-replay.md](04-trace-checkpoint-replay.md) | 实现事件日志、trace、checkpoint 和 replay。 |
| 5 | [05-research-domain-modeling.md](05-research-domain-modeling.md) | 新建 `business/research` 领域模型、端口、服务和 workflow spec。 |
| 6 | [06-research-single-paper-loop.md](06-research-single-paper-loop.md) | 跑通单篇论文分析闭环，使用 fake LLM，不做 UI。 |
| 6A | [06a-reader-repair-memory.md](06a-reader-repair-memory.md) | 加入 Reader Repair Memory / Repair RAG，把 reader 构建问题沉淀为可召回修复经验。 |
| 7 | [07-research-backend-interface.md](07-research-backend-interface.md) | 新增 Research 后端 service 和 API router，不复用旧 paper API。 |
| 8 | [08-framework-cleanup.md](08-framework-cleanup.md) | 清理旧框架层，保留有用资产，删除无用旧控制流和业务污染。 |
| 9 | [09-legacy-business-test-deletion.md](09-legacy-business-test-deletion.md) | 删除不服务新架构的旧业务、旧接口、旧测试和兼容逻辑。 |

## 推荐执行方式

每次只复制一个阶段文件给 Codex。每阶段必须完成：

1. 阅读本阶段文档和前序阶段产物。
2. 更新或创建对应 OpenSpec 任务。
3. 修改代码和测试。
4. 删除本阶段明确废弃的旧代码或旧测试。
5. 运行阶段要求的检查。
6. 提交变更。

## 全局验收命令

```powershell
openspec validate harness-research-runtime --strict
python -m scripts.dev compile
python -m scripts.dev test
python -m scripts.dev smoke
```

## 最终收敛形态

```text
framework/harness
framework/harness/skills/evolution
framework/llm
framework/tool
framework/memory
framework/skills
framework/artifacts
framework/events
framework/workers
framework/governance
framework/shared
business/research
business/research/reader_repair
interfaces/services/research_service.py
interfaces/api/routers/research.py
tests/framework/harness
tests/framework/harness/skills/evolution
tests/business/research
tests/interfaces/research
```

## 全局禁止事项

- 不做旧 paper_radar 兼容。
- 不把 Research 代码写进 `business/boards/paper_radar`。
- 不让 `business/research` import `interfaces` 或 `infrastructure`。
- 不让 LLM 返回值控制 workflow routing。
- 不让 LLM 直接修改、发布或激活生产 skill；skill 自进化必须经过 Harness gate、held-out eval、版本化发布和 rollback plan。
- 不让普通 Research/Reader run 因一次修复成功就修改 skill；Reader 修复经验必须先写 memory，再经 consolidate 和 skill evolution 晋升。
- 不允许没有 `max_replans`、`max_turns` 或 retry budget 的 Harness 运行循环。
- 不允许用 LLM 自评替代纯函数 VERIFY gate。
- 不用删除测试来掩盖失败；只有当旧行为明确废弃时才删除旧测试。
- 不保留仅为了旧接口、旧 payload、旧 UI、旧兼容存在的 adapter。
