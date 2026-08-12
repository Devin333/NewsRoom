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
| Agentic RAG 有界受控 | 多轮检索、读取、验证、补查和上下文组装必须由 Harness 控制；LLM 只能提出检索计划候选和证据摘要候选。 |
| Context Engineering 显式装配 | Worker 上下文必须由 Harness 按稳定前缀和动态尾部装配；规则、schema、gate、预算和 source refs 不允许被压缩丢失。 |
| 子 Agent 隔离 | 子 Agent 独立上下文、独立历史、显式 handoff、独立工具白名单和 memory namespace，不能互相污染。 |
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

## 阶段文档与执行顺序

编号保留主题分组，但实际执行必须按下面的依赖顺序，不按文件名排序执行。

| 执行顺序 | 阶段 | 文件 | 依赖 | 目标 |
| --- | --- | --- | --- | --- |
| 0 | 0 | [00-openspec-and-audit.md](00-openspec-and-audit.md) | 无 | 建立 OpenSpec change，审计现有代码和测试，形成 keep/adapt/delete 清单。 |
| 1 | 1 | [01-framework-harness-contracts.md](01-framework-harness-contracts.md) | 0 | 新增 `framework/harness` 核心契约和包结构。 |
| 2 | 2 | [02-state-machine-and-scheduler.md](02-state-machine-and-scheduler.md) | 1 | 实现 Harness 状态机、显式调度器、路由和重试策略。 |
| 3 | 3 | [03-seven-layer-ports.md](03-seven-layer-ports.md) | 1-2 | 建立七层可替换端口和 fake implementation。 |
| 4 | 3C | [03c-subagent-isolation.md](03c-subagent-isolation.md) | 3 | 建立通用子 Agent 隔离、显式 handoff、工具白名单、memory namespace 和独立 transcript。 |
| 5 | 3D | [03d-context-engineering.md](03d-context-engineering.md) | 3、3C | 建立 6 段上下文装配、stable prefix / dynamic tail、5 级压缩链路、context snapshot 和 replay 约束。 |
| 6 | 3B | [03b-bounded-agentic-rag.md](03b-bounded-agentic-rag.md) | 3、3D | 在 Harness 控制下建立多轮检索、读取、验证、补查和 RAGContextPack。 |
| 7 | 3A | [03a-skill-evolution.md](03a-skill-evolution.md) | 3、3B、3C、3D | 在 Harness 控制下建立 skills 自进化生命周期、候选仓、eval、晋升和回滚。 |
| 8 | 4 | [04-trace-checkpoint-replay.md](04-trace-checkpoint-replay.md) | 2、3A、3B、3C、3D | 实现事件日志、trace、checkpoint 和 replay。 |
| 9 | 5A | [05a-research-product-scenarios.md](05a-research-product-scenarios.md) | 0-4 | 明确 Research 产品场景，是阶段 5 的需求输入，不单独实现业务代码。 |
| 10 | 5 | [05-research-domain-modeling.md](05-research-domain-modeling.md) | 5A | 新建 `business/research` 领域模型、端口、服务和 workflow spec。 |
| 11 | 6 | [06-research-single-paper-loop.md](06-research-single-paper-loop.md) | 3B、3C、3D、4、5 | 跑通单篇论文分析闭环，使用 fake LLM，不做 UI。 |
| 12 | 6A | [06a-reader-repair-memory.md](06a-reader-repair-memory.md) | 3A、3B、3C、3D、4、5、6 | 加入 Reader Repair Memory / Repair RAG；必须在阶段 6 验收后开始，不与阶段 6 并行。 |
| 13 | 7 | [07-research-backend-interface.md](07-research-backend-interface.md) | 5、6 | 新增 Research 后端 service 和 API router，不复用旧 paper API。 |
| 14 | 8 | [08-framework-cleanup.md](08-framework-cleanup.md) | 0-7 | 清理旧框架层，保留有用资产，删除无用旧控制流和业务污染。 |
| 15 | 9 | [09-legacy-business-test-deletion.md](09-legacy-business-test-deletion.md) | 0-8 | 删除不服务新架构的旧业务、旧接口、旧测试和兼容逻辑。 |

## 专项增量 PRD

下列专项 PRD 基于前述 Harness + Research 基线追加，不修改阶段 0-9 的原始重建顺序，并按自身依赖和 OpenSpec change 独立交付。本索引只登记已纳入版本控制且已完成范围审查的专项文档。

| 阶段 | 文件 | 文档状态 | 实现状态 | 依赖 | 目标 |
| --- | --- | --- | --- | --- | --- |
| 18 | [18-artifact-boundary-integrity-hardening.md](18-artifact-boundary-integrity-hardening.md) | `FINAL` | `IMPLEMENTED` | 2026-07-10 artifact audit；2026-07-14 completion audit；不依赖阶段 10-17 | strict verified snapshot、transitive index/manifest integrity、store/reference/path closure、结构化 observability 与真实 adapter fail-closed 回归已完成；实现 `59e633e8`，归档 `7cf5e82e`。 |
| 19 | [19-durable-event-runtime-hardening.md](19-durable-event-runtime-hardening.md) | `READY_FOR_IMPLEMENTATION` | `IN_PROGRESS` | 阶段 4 的 trace/checkpoint/replay 语义；2026-07-14 `framework/events` live audit | 收敛 canonical event、durable append、per-stream ordering、outbox/inbox、retry/DLQ、deterministic replay、schema evolution 和 OTel/W3C propagation。 |
| 19A | [19a-event-record-envelope-migration.md](19a-event-record-envelope-migration.md) | `READY_FOR_IMPLEMENTATION` | `IN_PROGRESS` | 阶段 19；OpenSpec `durable-event-runtime` | 聚焦删除 framework legacy `EventRecord`、收敛 Recorder 单模型 API、迁移 workflow/checkpoint/JSONL、移除 Bus mixed payload，并以一版兼容期限完成最终删除。 |
| 20 | [20-framework-boundary-and-duplication-convergence.md](20-framework-boundary-and-duplication-convergence.md) | `READY_FOR_OPENSPEC` | `IN_PROGRESS` | 2026-07-18 框架层与重复实现专项审查；Harness gate 切片已实现并归档；Source 为 38/41；Research implementation `12ed843a` 已按 staged-only verified tree 完成 46/46 并归档；HAR-008..009 的 `harness-side-effect-authority-closure` 已由 `7caadd86` 完成实现，文档/evidence ledger 收口为 `51/51`；复用 `framework-runtime-safety-hardening`、`durable-event-runtime` | 已按 `decision -> effect -> durable outcome -> success` 收敛 Research hidden artifact preparation、controller-terminal atomic publication 和 run disposition/latest；该切片的 v2/reconciler、focused/broad/strict/smoke、baseline archive 与 staged release evidence 已完成，generic Tool/Memory 与 production skill release 仍由各自 owner 显式接入。Source 的 3.7、3.10、7.5，Research 的 RES-007、U7，以及阶段级 U9 保持开放；Quality/Workflow、budget/conversation/memory 与 legacy 候选继续按证据门拆分，不能凭目录或字段相似性直接合并/删除。 |
| 20A | [20a-harness-side-effect-authority-closure.md](20a-harness-side-effect-authority-closure.md) | `FINAL` | `IMPLEMENTED` | 阶段 20 的 HAR-008..009；OpenSpec `harness-side-effect-authority-closure`；Research composition baseline 与 `durable-event-runtime` projection | typed candidate、deterministic authority、decision/outcome recovery、Research hidden preparation、terminal atomic publication、accepted-only latest 与 provenance-bound skill release 已完成；当前台账 `51/51`，实现 commit `7caadd86`，文档/evidence 已完成收口；当前 change 仍待按流程归档。 |
| 22 | [22-attempt-scope-and-deadline-admission.md](22-attempt-scope-and-deadline-admission.md) | `READY_FOR_OPENSPEC` | `NOT_STARTED` | `attempt-execution-integrity-hardening`（`16/16`，实现 `e6cad121`，须先归档）；`framework-runtime-safety-hardening`；现有 Workflow / Tool / Parallel / Worker attempt contract | 保留 hard deadline、retry 总上限、bounded capacity、idempotency/reconciliation 和 indeterminate fail-closed 基线；把共享 `AttemptBudget` 拆为 root retry-credit ledger 与 per-operation local retry budget，移除 generic fencing 语义，并增加不足时间不启动的 deterministic deadline admission。 |
| 23 | [23-llm-cache-production-hardening.md](23-llm-cache-production-hardening.md) | `FINAL` | `IMPLEMENTED` | 现有 `framework/llm/cache`、`framework/llm/routing`、`GlobalBudgetTracker`、`LLMStreamAccumulator`；专用 Redis cache adapter；不替换 Harness durable state | 将开发期 `InMemoryLLMCache + CachedLLMClient.complete()` 收敛为 router 协作的 exact response cache：versioned scope-bound key、deterministic eligibility、cooldown/budget 前 lookup、primary/fallback 隔离、Redis TTL/atomic single-flight、完整 stream replay、fail-open 与 durable cache events。 |
| 24 | [24-model-aware-context-runtime-hardening.md](24-model-aware-context-runtime-hardening.md) | `READY_FOR_OPENSPEC` | `NOT_STARTED` | 阶段 3D Context Engineering；旧 `llm-context-guard`（`8/8` complete，但仅为 estimate-and-signal MVP）；`ModelCapabilities`；阶段 19 canonical durable event owner | 建立 resolved-deployment-aware request preparation/token preflight、output reserve、message/tool transaction atomicity、证据安全的 bounded compaction、压缩后 deterministic VERIFY、durable replay 与 production LLM callsite 收敛；明确替换 FIFO `pop(0)`、无行为 strategy 和 false verified。 |
| 25 | [25-structured-output-contract-hardening.md](25-structured-output-contract-hardening.md) | `READY_FOR_OPENSPEC` | `NOT_STARTED` | 已完成的 `llm-structured-output` / `llm-structured-output-validation`；`jsonschema`、Pydantic；阶段 19 durable events；阶段 23 cache 与阶段 24 context 的接口契约 | 把 parse-only / 手写 subset validator 收敛为 strict JSON object decoder、local Draft 2020-12 schema gate、Pydantic typed re-validation、Provider capability projection、complete/stream/cache 一致性，以及 Harness 有界 repair/replay；Provider strict 或 constrained decoding 只作可测的生成约束，不替代本地真相。 |
| 26 | [26-unified-budget-governance.md](26-unified-budget-governance.md) | `FINAL` | `IMPLEMENTED` | 阶段 20 的 `WF-002/U10`；现有 `framework/llm/budget`、Agent/Workflow 重复 `GlobalBudget*`；阶段 22 retry-credit 边界；阶段 23 cache 与阶段 24 context 接口 | 已将跨调用累计的 LLM calls/tokens/cost 收敛到 `framework/governance/budget`，完成显式 scope、原子 reservation、exactly-once settlement、并发 admission、durable events、snapshot/restore/replay，以及 Router/Agent/Workflow/Harness cutover；per-call、context、loop/stall/output、retry、tool/wall-time 与 diagnostics 仍由各自 owner 保持。实现与验证证据见 `openspec/changes/framework-budget-contract-convergence/evidence.md`。 |
| 27 | [27-agent-session-retirement-and-subagent-transcript-durability.md](27-agent-session-retirement-and-subagent-transcript-durability.md) | `READY_FOR_OPENSPEC` | `NOT_STARTED` | 阶段 3C、阶段 4、阶段 20；现役 Harness TaskPlan/SubAgent/Context/Memory；旧 `paper-agent-shared-session-analysis` | 先以 `harness-durable-subagent-transcript` 闭合 production transcript body/receipt/TaskPlan event lineage、restart/replay 与 fail-closed，再以独立 change 删除无人构造的 `framework/agent/session`、`framework/memory/session`、AgentLoop hook 和专用 tests；禁止 AgentRunner session integration，并用 `archive --skip-specs` 保留旧 change 历史而不污染 canonical specs。 |

依赖解释：

- 3C 先定义子 Agent 隔离和 handoff；3D 再把通用 `ContextEnvelope` 映射到子 Agent context。
- 3D 先定义上下文装配协议；3B 再把 `RAGContextPack` 接入 Context Engineering。
- 3A 最后做 skill evolution，因为它会消费 RAG、SubAgent、Context 和端口能力。
- 4 是 durable trace/replay 的完整实现；3A/3B/3C/3D 只需先写事件契约和 refs，完整 replay 在阶段 4 收口。
- 19 不替换阶段 4 的 Harness 控制语义，而是把阶段 4 的 event/transcript/replay 约束生产化：统一 `framework/events`、Workflow/Harness live durable write、storage delivery ledger、schema 演进和标准 trace propagation；第一版不引入外部 broker。
- 19A 不是新的独立 capability 或 OpenSpec change；它是阶段 19 的聚焦实施切片，复用 `durable-event-runtime` 的 canonical `StoredEvent`、migration 和 deletion tasks，禁止把 `EventEnvelope` 变成第二个永久 durable model。
- 20 是 2026-07-18 专项审查后的 umbrella PRD，必须拆分为独立 OpenSpec changes；它复用 Research production composition 和 framework runtime safety 的既有 owner，并把阶段 19 的 durable transcript 当作依赖，不得并行重写 canonical event/replay contract。
- 20A 是阶段 20 的第一个聚焦交付文档，只承接 `harness-side-effect-authority-closure`；它不替代 umbrella PRD，也不接管 generic Tool、Workflow、Event schema、Redis 或 MCP/OpenAPI owner。
- 22 是 `attempt-execution-integrity-hardening` 的后续语义收敛，不回退其副作用安全、层级幂等键、resource-issued lease、bounded capacity 或 indeterminate publication guard；实施前必须先归档完成态 baseline，再以新 OpenSpec change 替换“父子共享一个 local attempt budget”的旧 requirement。
- 23 是 LLM response cache 的生产化专项；它只缓存 exact、无 tool、副作用安全且带 dependency revision 的完整 `LLMResponse`，不替代 Harness transcript、TaskPlan、memory、evidence 或 artifact store。实施前必须创建并严格校验 `llm-cache-production-hardening`，且 cache hit 不得改变 deterministic route、quality gate 或 publication 语义。
- 24 把阶段 3D 的语义 Context Engineering 与 `framework/llm/context` 的模型物理窗口 preflight 接起来：Harness 继续决定内容选择、保护、压缩和 VERIFY，LLM 层只负责 resolved deployment 的实际 payload 计数与 admission。它替换旧 `llm-context-guard` 的窄范围 requirement，并为阶段 23 cache 提供 admitted `PreparedLLMRequest`/fingerprint 前置契约；不得把 summary candidate、provider overflow 或 cache hit 当作绕过 deterministic gate 的理由。
- 25 把既有 `llm-structured-output` / `llm-structured-output-validation` 的 parse/subset 起点生产化：`framework/llm/structured_output` 负责 schema preflight、strict decode、本地 Draft 2020-12 validation 与 Provider projection；Harness 继续独占 repair/replan/halt、domain/evidence quality 与 publication 决策。阶段 24 必须把最终 schema/projection payload 纳入 context accounting，阶段 23 必须把 contract digest 纳入 exact cache identity，阶段 19 继续持有 durable event/transcript；25 不新建第二个 event/cache/context owner，也不把 Provider `strict` 误作最终 schema pass。
- 26 承接阶段 20 的 conditional `WF-002/U10`，先比较 router、Agent、Workflow 的 logical input/output、reservation、settlement、cost rounding、exception 与 lifecycle，再只合并确认重叠的累计 LLM calls/tokens/cost contract。canonical ledger 由 `framework/governance/budget` 拥有，`framework/llm/budget` 保留 per-call policy、pricing 与 usage adapter，Agent 保留 loop/stall/output，Workflow 保留 tool/wall-time，阶段 22 保留 retry credits，阶段 24 保留 context admission；budget module 只返回 deterministic decision，最终 retry/replan/approval/halt 仍由 Harness 决定。
- 27 承接阶段 3C 的 isolated subagent transcript 和阶段 4 的 durable replay 要求，并落实阶段 20 的 legacy retirement 原则。它必须拆成两个顺序 change：先让 production `SubAgentRuntime` 使用可校验 durable transcript store，并把 receipt 写入 TaskPlan result/event lineage；replacement acceptance 通过后，才删除旧 shared-agent-session runtime。`framework/agent/session` 不得接入 `AgentRunner`，旧 `paper-agent-shared-session-analysis` 不得普通 archive 到 main specs，只能在 retirement 完成后使用 `--skip-specs` 保存历史。
- 5A 是需求澄清文档，5 是实现文档；如果只复制一个阶段给 Codex，必须先复制 5A 再复制 5。

## 推荐执行方式

每次只复制一个阶段文件给 Codex。每阶段必须完成：

1. 阅读本阶段文档和前序阶段产物。
2. 更新或创建对应 OpenSpec 任务。
3. 修改代码和测试。
4. 删除本阶段明确废弃的旧代码或旧测试。
5. 运行阶段要求的检查。
6. 提交变更。

如果阶段文档引用了后续阶段的概念，除非依赖表把它列为硬依赖，否则只按“接口预留”处理，不要为了满足引用而提前实现后续阶段。

## 全局验收命令

```powershell
openspec validate --all --strict
python -m scripts.dev compile
python -m scripts.dev test
python -m scripts.dev smoke
```

## 最终收敛形态

```text
framework/harness
framework/harness/skills/evolution
framework/harness/rag
framework/harness/subagents
framework/harness/context
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
business/research/paper_card
business/research/taxonomy
business/research/reader
business/research/reader_repair
business/research/reading_session
business/research/code_repository
business/research/benchmark
business/research/method_graph
business/research/agent_intelligence
business/research/rag
interfaces/services/research_service.py
interfaces/api/routers/research.py
tests/framework/harness
tests/framework/harness/skills/evolution
tests/framework/harness/rag
tests/framework/harness/subagents
tests/framework/harness/context
tests/business/research
tests/interfaces/research
```

## 全局禁止事项

本节是通用规则的权威来源。各阶段文档只补充本阶段特有约束；如果阶段文档和本节措辞冲突，以本节为准，并优先修正文档而不是在代码里兼容两套规则。

- 不做旧 paper_radar 兼容。
- 不把 Research 代码写进 `business/boards/paper_radar`。
- 不让 `business/research` import `interfaces` 或 `infrastructure`。
- 不让 LLM 返回值控制 workflow routing。
- 不让 LLM 决定 RAG 检索路由、停止条件、证据采纳、memory 写入或 skill 晋升。
- 不让子 Agent 共享 raw context、private history、hidden prompt、sibling transcript、tool allowlist 或未授权 memory namespace。
- 不让子 Agent 之间隐式传递信息；跨子 Agent 信息必须通过 Harness-approved handoff 和 schema gate。
- 不让 LLM 直接修改、发布或激活生产 skill；skill 自进化必须经过 Harness gate、held-out eval、版本化发布和 rollback plan。
- 不让普通 Research/Reader run 因一次修复成功就修改 skill；Reader 修复经验必须先写 memory，再经 consolidate 和 skill evolution 晋升。
- 不允许没有 `max_replans`、`max_turns` 或 retry budget 的 Harness 运行循环。
- 不允许没有 `max_rounds`、`max_queries`、`max_source_reads`、`max_memory_hits` 或 context budget 的 RAG 循环。
- 不允许把工具结果、RAG 动态结果、用户私有记忆、reader payload 或 transcript 摘要放进 stable prefix。
- 不允许压缩 Global Policy、workflow route table、schema、gate definition、tool allowlist、memory namespace policy、source refs 或预算值。
- 不允许用 LLM 自评替代纯函数 VERIFY gate。
- 不用删除测试来掩盖失败；只有当旧行为明确废弃时才删除旧测试。
- 不保留仅为了旧接口、旧 payload、旧 UI、旧兼容存在的 adapter。
