# 阶段 20：框架边界与重复实现收敛 PRD

> Document status: READY_FOR_OPENSPEC
>
> Implementation status: IN_PROGRESS
>
> Version: v1.15
>
> Priority: P1（控制权与生产运行阻断）/ P2（架构与契约收敛）
>
> Scope: Harness VERIFY authority、Research production composition、Tool approval/policy、Source governance、Analysis quality、Workflow/framework contract 与 legacy cleanup
>
> Source audit: 2026-07-18 审查基线为 tracked HEAD `e1cd72f3` + 当时 dirty/untracked working tree（包含未跟踪的 `infrastructure/research/`）；该 commit 只标识 tracked baseline，不是完整可重放快照
>
> PRD revision baseline: Research implementation `12ed843a` + 2026-07-20 当前 dirty working tree；历史审查快照、已交付实现与其他并行改动必须分开解释
>
> Existing OpenSpec owners: `research-runtime-production-composition`、`framework-runtime-safety-hardening`、`durable-event-runtime`
>
> Completed OpenSpec slice: `harness-deterministic-gate-enforcement`（ARCHIVED；implementation `017a227e`；archive `2026-07-18-harness-deterministic-gate-enforcement`）
>
> Active OpenSpec slices: `source-policy-contract-convergence`（IN_PROGRESS）与尚未归档的 `research-runtime-production-composition`（implementation tasks `46/46`；唯一进度台账见第 1.1 节，其他章节不得复制任务数字作为完成证据）
>
> Depends on: 阶段 1/2 Harness authority、阶段 8/9 legacy deletion rules、阶段 19 durable gate-event contract，以及上述 active changes 的明确 file ownership
>
> Last updated: 2026-07-20

> 状态说明：`READY_FOR_OPENSPEC` 表示问题、目标、非目标、ownership、兼容边界、实施顺序和验收标准已经形成 PRD 基线，但本 PRD 不授权把全部工作塞进一个 change。`IN_PROGRESS` 仅表示至少一个独立实施批次已开始，不代表阶段 20 整体完成。每个实施批次必须先建立或更新对应 OpenSpec delta，并通过 strict validation。文档被后续 PRD 取代时标记 `SUPERSEDED`。

## 0. 一句话结论

NewsRoom 当前最需要的不是增加新的 framework abstraction，而是让已经存在的运行能力回到唯一权威路径：**Harness 的 deterministic gate 必须是 quality/routing 的唯一事实源，Research 默认入口必须进入真实 runtime，approval/tool/source/quality/workflow 等共享契约必须各有一个 canonical owner。**

本阶段以小步、可回滚的 contract convergence 取代大规模重写。它保留现有公共 API、持久化格式、event replay、合法 backend 变体和已验证的 Harness 有界状态机，只收敛已经通过调用关系、运行探针或测试门禁证明存在的冲突实现。

---

## 1. 背景与审查依据

### 1.1 审查起点与当前验证状态

截至 2026-07-18，审查基线（tracked HEAD `e1cd72f3` + 当时 dirty/untracked working tree）的会话验证结果为：

| 检查 | 结果 | 说明 |
| --- | --- | --- |
| `python -m scripts.dev smoke` | `1014 passed, 23 skipped, 1 failed` | 唯一失败为 infrastructure boundary test，报告 7 个 `infrastructure/research -> business` imports |
| Source focused suite | `67 passed` | 现有 happy path 通过，但未覆盖跨入口 policy parity |
| Analysis quality focused suite | `38 passed` | 两套 quality 实现各自通过，未覆盖生产/评估 parity |
| Research/RAG route suite | `20 passed` | 主要依赖注入 fake 或显式 service，未证明默认 production composition |
| Workflow contract suite | `31 passed` | 未覆盖 fallback-only graph 的 compiler/runtime parity |
| `openspec validate --all --strict` | 510 项通过 | 说明规格语法有效，不代表 live implementation 已满足全部约束 |
| `git diff --check` | 通过 | 当前审查没有格式错误证据 |

上述历史数字来自审查会话记录，仓库中没有保存完整 suite 选择命令与原始日志；尤其 7 个 `infrastructure/research -> business` imports 位于当时未跟踪文件中，不能由 `e1cd72f3` 单独重放。因此这些数字只作为问题发现基线，不作为任何切片的 release evidence；可重放结论必须引用 committed regression、OpenSpec `evidence.md` 或当前重新执行的命令结果。

截至 2026-07-20，本 PRD 定稿时获得以下验证证据；其中 Research delivery 行来自隔离 staged-only candidate，其余行来自标明的当前 dirty working tree：

| 当前检查 | 结果 | 结论边界 |
| --- | --- | --- |
| Source composition/persistence focused selection | `30 passed` | 覆盖 Source runtime provider、Research arXiv shared-ledger denial、URL/SourceError persistence/replay 和 Research URL identity compatibility；不是完整 Source suite |
| `tests/architecture/test_infrastructure_boundary.py` | `4 passed` | 证明当前精确 allowlist 与已扫描 import 一致；不自动证明每个新增 exception 的 ownership 正确 |
| `openspec validate source-policy-contract-convergence --strict` | 通过 | 只证明 active change 语法与 schema 有效 |
| `openspec validate --all --strict` | `508 passed, 0 failed` | 只证明当前全部 OpenSpec artifacts 可验证 |
| `git diff --check` | 通过 | 有 CRLF -> LF 警告，但没有 whitespace error |
| Research staged-only candidate `59a92c90` | recorded production `2 passed`；durable dependency `3 passed`；mandatory smoke `1304 passed, 23 deselected, 20 warnings`；Source validation `0` errors/warnings；isolated OpenSpec `181 passed, 0 failed`；diff check 通过 | candidate 与 implementation `12ed843a` 共享 tree `d433ca469a0f...`，相对 parent `8693833c` 恰为 `95` paths；证明 delivered snapshot，不证明 live arXiv/LLM ready |

其中 Source focused selection 使用以下可重放命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/interfaces/services/test_source_runtime_composition.py `
  tests/interfaces/services/test_source_research_rate_limit.py `
  tests/contracts/test_source_url_persistence_compatibility.py `
  tests/contracts/test_source_error_persistence_compatibility.py `
  tests/business/research/test_source_url_identity_compatibility.py
```

上述结果不替代各实施切片的完整 focused tests、mandatory smoke 或真实 backend contract gate。

以下是本 PRD 内唯一的实施进度台账，`as_of_head=12ed843a`、`as_of_date=2026-07-20`。`task ledger` 不替代 committed implementation、测试日志或 `evidence.md`；第 14、17、21 节只引用本表，不再复制任务数字。

| Active change | Committed evidence baseline | Current task ledger | Open tasks / blocker | 解释 |
| --- | --- | --- | --- | --- |
| `source-policy-contract-convergence` | implementation `372027ac`；URL、limiter/retry、taxonomy、mapper 与兼容读取已有 core evidence | `38/41` | `3.7`、`3.10`、`7.5` | Research/entry/Harness composition 与 release/operator evidence 尚未全部闭环，不能宣称 change complete |
| `research-runtime-production-composition` | implementation `12ed843a`；tree `d433ca469a0f...`；staged-only candidate `59a92c90` 与 final commit tree 相同；`95` delivered paths | `46/46` | change 内 implementation task 无开放项；U7 live provider qualification、U9 operator release evidence 和外部 owner 的 `RES-007` 仍开放 | `RES-001..006`、`RES-008..011` 已交付；该 change 尚未归档且阶段 20 仍有 Tool、Quality、Workflow、Source、legacy 等切片，不能据此宣称 umbrella complete |

现有 Harness 在 `PLAN -> EXECUTE -> VERIFY`、`max_turns`、`max_replans`、retry budget 和 durable transition 方面有明确实现与测试。本阶段不替换这套状态机，只修复 VERIFY authority 和外围 composition/contract 漂移。

### 1.2 审查起点已确认问题与当前状态

下表记录上述审查基线确认的问题定义和当时证据，不表示所有问题在当前 `HEAD` 仍可复现。H1/H2 已由 `017a227e` 修复并归档；其他切片的当前状态以第 17.1 节为准。保留审查起点证据是为了维持 finding -> requirement -> regression 的可追踪性。

| ID | 级别 | 已确认问题 | 关键证据 | 实际后果 |
| --- | --- | --- | --- | --- |
| H1 | P1 | Worker 自报 `quality_score` 会被转成 `HarnessQualityVerdict` 并参与 `ON_VERDICT` 路由 | `framework/harness/workers/result.py:18-35`；`framework/harness/control_plane/harness.py:1572-1589`；`framework/harness/control_plane/routing.py:70-87` | LLM/subagent 可间接决定 quality 和下一步 |
| H2 | P1 | `HarnessStepSpec.quality_gate` 只被序列化，没有 fail-closed registry 绑定 | `framework/harness/workflow/step.py:68-98`；`framework/harness/control_plane/harness.py:1033-1040` | workflow 声明的 gate 可能从未执行或进入 replay |
| R1 | P1 | 默认 HTTP/MCP 构造裸 `ResearchApplicationService`，固定使用 unconfigured use case 和进程内 store | `interfaces/api/app.py:102-123`；`interfaces/services/research_service.py:100-110,315-323,485` | 真实 `source -> evidence -> analysis -> quality -> artifacts` 链路在默认入口不可达 |
| T1 | P1 | `ToolApprovalRequest.to_worker_approval_request()` 返回 tool 模块中的重复 DTO | `framework/tool/governance/approval.py:64-150`；`framework/workers/approval/model.py:74-167` | approval 幂等、secret validation、status 和序列化依赖 store backend |
| T2 | P2 | Framework、infrastructure、business 和 `ToolPolicy` 各自维护危险工具分类 | `framework/tool/registry/catalog.py:192-201`；`infrastructure/tools/catalog.py:146-155`；`business/tools.py:204-230`；`framework/tool/models/policy.py:154-168` | 同一个 ToolDefinition 在 discovery/schema/executor 中可能得到不同授权结论 |
| B1 | P2 | Research/Harness adapter ownership 与 architecture test 不一致 | `business/research/services/rag_policy.py:3-70`；`business/research/application/paper_rag_session.py:5-115`；`tests/architecture/test_infrastructure_boundary.py:24-34` | business application 直接构造 Harness DTO/controller，同时合法 outbound adapter 无法通过 smoke |
| S1 | P2 | URL、rate limiter、retry、error taxonomy 和 mapper 存在重复及行为漂移 | `business/layers/signal/source_processing/url_normalization.py:10-43`；`business/layers/signal/source_tool_runtime.py:43-87,171-202`；`infrastructure/external/sources/fetch_policy.py:88-172` | quota 分裂、retry 结论不一致、canonical id 漂移和 lineage 字段丢失 |
| Q1 | P2 | 生产 `quality_records.py`、评估 `analysis/quality/*` 和 Research gate 三条质量路径并存 | `business/layers/analysis/tools.py:8-17,88-139`；`business/layers/analysis/quality/eval_dataset.py:69-95` | 同一 report/evidence 在不同入口可能得到不同 pass/score |
| W1 | P2 | Spec validator、compiler 和 runtime 对 fallback edge 的 graph 语义不一致 | `framework/specs/validation.py:171-190`；`framework/workflow/compiler/compiler.py:221-251`；`framework/workflow/runtime/execution_loop.py:626-679` | 合法 recovery workflow 可能通过 spec validation 却无法 strict compile |
| E1 | P2 | Research 返回未持久化的 `skill_experience_refs`，并写入固定伪 package hash | `business/research/application/single_paper_runtime.py:586-650` | experience 无法查询/replay，skill provenance 不可信 |

C1（budget/conversation/memory contract）与 D1（legacy builder/facade）是审查起点的候选项，不列入上表“已确认问题”：C1 尚缺同一 logical input 的 A/B parity、生产调用方和 persistence lifecycle 证据；D1 只完成仓内静态引用探针，尚缺 public export、dynamic entry、包外 consumer 与 replay 审计。两者分别由第 22 节 U10 与 U6 控制；证据未齐时保留现状，不得据此合并或删除。

### 1.3 审查起点反例探针

以下探针均在上述 tracked + dirty/untracked 审查基线上执行，未修改当时工作树。H1/H2 对应探针已在后续归档切片中转为 committed regression；其余结果仍是对应切片的修复前 observation，只有转成 committed regression 后才算可重放 evidence：

| Probe | 审查起点结果 | 目标结果 |
| --- | --- | --- |
| LLM step 声明不存在的 `quality_gate="DefinitelyMissingGate"` | run 仍为 `succeeded` | compile 或 run start 前 fail-closed |
| LLM worker 返回 `quality_score=0.95` | 形成 verdict 并按 `ON_VERDICT` 路由 | 只能作为 candidate observation，不能直接形成 verdict |
| Tool approval 转换类型检查 | 返回类型不属于 worker `ApprovalRequest` | 返回 canonical worker model |
| InMemory approval 重复 decision | 第二次 decision 仍成功 | 抛出稳定 `ApprovalAlreadyDecidedError` |
| read-only ToolDefinition 危险分类矩阵 | `mcp.foo`、`source.fetch_url`、`local_json.save`、`qdrant.upsert` 结论不一致 | 所有入口使用同一 policy decision |
| fallback-only workflow | spec validation 通过，strict compiler 报 `unreachable_step` | validator/compiler/runtime 使用同一 graph |

实施每个对应切片的修复前，必须先把相关探针转成可复现的本地 failing regression，并把 red 命令、失败 oracle 和结果记录到 OpenSpec `evidence.md`；regression 与根因修复随后以 green implementation commit 提交。已归档切片保留其 regression，不要求为了文档顺序重演历史失败提交。聊天记录和本 PRD 中的输出不能替代可重复测试。

### 1.4 重复分类与结论边界

本 PRD 只把行为、输入输出和真实调用路径重叠的实现列为收敛对象。以下分类是后续 OpenSpec 和删除决策的约束，不允许仅凭文件名或代码形态改变分类。

| 分类 | 当前结论 | 代表范围 | 处理原则 |
| --- | --- | --- | --- |
| 真正的重复实现 | 已确认 | Source URL/retry/taxonomy/error construction、Tool risk decision、Workflow adjacency | 选定 canonical owner，以 contract test 迁移调用方，再删除算法副本 |
| 有意保留的变体 | 已确认 | Marker/MinerU/Nougat/PyMuPDF parser；Local JSON/PostgreSQL/Redis/Qdrant backend；Source business DTO 与 infrastructure transport DTO | 保留各自 I/O、事务、部署或领域生命周期，只共享 deterministic contract 和 mapper |
| 仅表面相似 | 已确认 | `/ask` 与 `/rag-ask`；MCP server 入站接口与 ToolRuntime 出站 MCP adapter；Research-specific gate 与共享 citation/support gate；外层 `HarnessWorkflowSpec` 与内层 `RAGSessionSpec` | 不合并职责；通过显式 mode、port、parent/child run identity 和依赖测试防止互相替代或形成第二条外层控制路径 |
| 死代码候选 | 部分确认 | 私有 legacy builder、薄 facade、旧 Workflow/Agent control-plane exports | 仓内不可达不等于可安全删除；必须补齐 public export、dynamic entry、外部 consumer 和 replay 审计 |
| 待验证疑似问题 | 未确认 | budget/conversation/memory DTO、test fixture/mock/setup、pagination/config/serialization helper、旧 report DTO、重复 storage adapter | 在获得生产调用和契约重叠证据前不进入删除或合并范围，统一登记在第 22 节 |

### 1.5 重叠证据台账与文档边界

本文件是把专项审查结论转换为目标、需求、ownership 和验收门的整改 PRD，不替代按 P0-P3 编排的六部分审查报告。阶段 0 的 legacy 范围清单保存在 [`audit-inventory.md`](audit-inventory.md)；本 PRD 的问题证据以第 1.2、1.3、1.5 和 17.1 节为准。下表只列行为、输入输出和生产调用职责均已确认重叠的项；不能满足相同门槛的候选统一留在第 22 节。

| Finding | 实现 A | 实现 B / 调用关系 | 重叠证据与为何不是策略变体 | 收敛结论 | 置信度 |
| --- | --- | --- | --- | --- | --- |
| T1 approval DTO | `framework/tool/governance/approval.py:64-150` 的 `ToolApprovalRequest` 转换与 tool lifecycle | `framework/workers/approval/model.py:74-167` 的 worker `ApprovalRequest`，由 approval store/worker lifecycle 消费 | 两者承载同一 request id、pending/decision/status/expiry 语义；反例探针证明转换结果甚至不是 worker canonical type。backend I/O 可以不同，approval 状态机不能随 store 改变 | `framework/workers/approval` 拥有 generic model；tool 层只保留 tool-specific input 与显式 mapper | 高 |
| T2 tool risk decision | `framework/tool/registry/catalog.py:192-201` 与 `framework/tool/models/policy.py:154-168` | `infrastructure/tools/catalog.py:146-155`、`business/tools.py:204-230`；catalog/schema/executor/inspection 最终都消费同一 `ToolDefinition` | 输入是同一 tool metadata，输出都是 risk/approval decision；read-only golden matrix 已出现入口间分歧，因此不是 provider-specific capability 差异 | `framework/tool` policy/governance 为唯一 decision owner；各 catalog 只追加 inventory | 高 |
| S1 retry/quota/taxonomy | `business/layers/signal/source_tool_runtime.py:43-87,171-202` | `infrastructure/external/sources/fetch_policy.py:88-172`；source tool、connector、health/Research fetch 路径分别调用 | 两条路径对同一 URL/domain、异常和 attempt budget 决定 quota、retry 与错误分类；调用入口不应改变 attempts 或 canonical denial。connector-specific diagnostics 保留在 adapter，不是重复 policy 的理由 | `fetch_policy.py` 执行统一 policy，business 暴露 port/decision contract；URL identity、taxonomy、mapper 分别归第 6.2 节 owner | 高 |
| Q1 shared analysis quality | `business/layers/analysis/tools.py:8-17,88-139` 的 production quality path | `business/layers/analysis/quality/eval_dataset.py:69-95` 与 Research quality projection | production/eval 对同一 report/evidence 的 citation、support、score/editor 规则产生 pass/score；Research readiness 有额外领域输入，明确保留为 adapter，不把它误并入共享算法 | `business/layers/analysis/quality` 拥有共享 engine；Research 只保留领域增量 gate，先做 golden parity 再切换 | 中高 |
| W1 workflow graph semantics | `framework/specs/validation.py:171-190` | `framework/workflow/compiler/compiler.py:221-251`、`framework/workflow/runtime/execution_loop.py:626-679`；三者消费同一 `WorkflowSpec` | fallback-only 反例中 spec validation 通过而 strict compiler 判 `unreachable_step`；fallback edge 是否参与 reachability 是同一图事实，不是 compiler/runtime 策略差异 | stdlib-only `framework/specs/graph_semantics.py` 作为 pure owner，validator/compiler/runtime 共同消费 | 高 |

---

## 2. 用户、场景与产品价值

### 2.1 目标用户

| 用户 | 需要解决的问题 |
| --- | --- |
| API/MCP/CLI 调用方 | 默认 Research 能稳定执行真实分析，或返回可操作的配置错误，而不是永久 503 |
| Operator/Reviewer | quality、approval、publication 和 replay 决策可追踪到确定性规则与持久化记录 |
| Framework maintainer | 每个共享 policy/DTO/graph 只有一个 canonical owner，不需要猜测入口差异 |
| Research developer | 只实现 Research domain/use case，不在 application/service 内装配 Harness controller 或 concrete store |
| Test maintainer | contract suite 能覆盖所有 backend/transport，而不是复制 fake scaffolding 固化不同语义 |

### 2.2 关键场景

1. 一个 configured 默认 API 实例收到论文分析请求，进入真实 Research/Harness runtime，完成 quality gate 后持久化 artifacts、run record、trace 和可查询 experience ref。
2. 一个 LLM worker 返回很高的自评分数，但 deterministic gate 失败，Harness 必须按 gate 结果 replan/retry/halt，不能按 worker 分数放行或路由。
3. 一个高风险工具从 CLI、MCP、Agent 或 Workflow 进入系统，所有入口得到相同风险分类和 approval request，重复审批被拒绝。
4. RSS、HTML、health probe 和 source tool 请求同一域名时，共享同一个 domain quota，并对同一个异常得到相同 retry/taxonomy 结论。
5. 同一个 report/evidence fixture 经 production tool、eval 和 Research projection 后，共享规则得到同一判定；领域特有差异被显式记录，而不是隐藏在平行实现中。

---

## 3. 产品目标与成功指标

### 3.1 目标

| 目标 | 定义 |
| --- | --- |
| G1：恢复 Harness authority | routing、quality verdict、authorization、memory write 和 publication 只由 deterministic controller/gate/policy 决定 |
| G2：打通默认 Research runtime | configured HTTP/MCP/CLI 默认入口复用同一 production factory 与 durable store |
| G3：建立单一 contract owner | approval、tool risk、source policy、quality、workflow graph 和 shared DTO 各有一个权威实现 |
| G4：保持兼容 | 公共 API、持久化 schema、event replay、artifact refs 和合法 backend 变体不被无计划破坏 |
| G5：受控删除 legacy | 只有在生产调用、包外 API、动态 import 和 replay compatibility 证据齐全后才删除旧实现 |

### 3.2 可量化成功指标

| 指标 | 验收阈值 |
| --- | --- |
| 未解析的 step quality gate | `0`；任何未知 gate 在执行前失败 |
| Worker 输出直接形成 quality verdict 的路径 | `0` |
| Harness 状态机边界 | 每个 run 只按合法 `PLAN -> EXECUTE -> VERIFY` transition 推进；`max_turns`、`max_replans` 与 retry budget 在边界值耗尽后不再产生 worker/gate 调用 |
| Durable phase event 完整性 | 每次 phase transition、retry/replan decision 和 terminal state 均有单调有序、可去重的 durable event；replay 后 state/counter/scheduler decision 100% 一致 |
| Artifact namespace 隔离 | accepted output 只进入 canonical/published store；失败、halted、待审批 candidate/diagnostic 只通过 quarantine reader 可见，published/latest index 可见数为 `0` |
| Configured 默认 Research 成功路径 | 六个 Research/MCP entry surfaces 解析到同一 factory implementation/object-graph contract；不包含 unconfigured use case 或 in-memory production store |
| Approval canonical model | ToolExecutor、InMemory、LocalJson 及 interface service 类型/状态语义 100% 一致 |
| Tool risk parity | 同一 ToolDefinition 在 catalog、schema export、executor、inspection 中决策 100% 一致 |
| Source policy parity | URL golden、retry matrix、taxonomy、shared quota 和 `SourceError` round-trip 100% 通过 |
| Source public payload parity | `RawSourceItem` 17 个公开字段、lineage、artifact refs、nested metadata 和 UTC `Z` 在 API/MCP/worker/CLI/tool 路径 100% 一致 |
| Production quality owner | 每个共享 citation/support/score/editor 规则只有一个生产实现 |
| Workflow graph parity | fallback-only、failure edge、cycle、dataflow 和 runtime route 使用同一 adjacency contract |
| Research workflow/session ownership | Recorded production analysis run 引用 canonical workflow id/version/checksum 并产生对应 phase/gate events；bounded RAG session 不成为第二个外层 workflow |
| Mandatory smoke | `0 failed`；architecture tests 无未文档化 allowlist |
| Legacy 调用 | 被标记删除的私有路径仓内引用为 `0`；公共 export 删除前有明确 migration evidence |

---

## 4. 非目标

- 不重写整个 framework、Harness、Workflow 或 Research。
- 不引入新的 orchestration framework、broker、workflow engine 或依赖注入框架。
- 不修改 UI，不新增产品页面。
- 不替换阶段 19 的 durable event、ordering、outbox/inbox、replay 或 OTel 设计。
- 不把 Marker、MinerU、Nougat、PyMuPDF、single-backend 和 cascade parser 强行合并；它们是明确策略变体。
- 不合并 Local JSON、PostgreSQL、Redis、Qdrant 等 backend 的 I/O、事务、锁或部署生命周期；只共享 deterministic contract/policy。
- 不把 Source business DTO 与 infrastructure transport DTO 机械合并；允许显式 mapper 和不同演进生命周期。
- 不要求 ordinary smoke 使用 live credentials 或网络服务。
- 不为减少文件数而保留 god module，也不创建新的无 owner `shared/utils` 桶。

---

## 5. 系统不变量

### 5.1 Harness authority

- Worker 只能返回 candidate、artifact refs、diagnostics 和 observations。
- Worker 自报分数、标签或建议不得直接成为 `HarnessQualityVerdict`、route、approval、memory write 或 publication decision。
- VERIFY verdict 必须带 gate id、gate version、deterministic input refs 和 result，并写入 durable transcript。
- 声明了 `quality_gate` 的 step 不允许在 gate 未解析、未执行或结果缺失时成功。

### 5.2 One owner per decision

- 同一种风险分类、canonicalization、retry、quality 或 graph 规则只能有一个权威实现。
- Adapter 可以投影数据，但不能复制决策规则。
- Backend 可以实现不同 I/O，但必须运行同一 contract suite。

### 5.3 Layer ownership

| 层 | 允许职责 | 禁止职责 |
| --- | --- | --- |
| `interfaces/api`、`interfaces/cli`、`interfaces/mcp` | transport parsing、actor/request context、调用 application-layer service 或明确获批的 application use case | 构造 process-global business runtime、直接访问 executor/store |
| `interfaces/composition` | 选择 concrete adapters、settings、lifecycle/cache | 表达 Research 业务规则或复制 authorization policy |
| `business/research` | domain model、use case、candidate worker contract、deterministic Research rules、声明式 workflow metadata；指定 runtime boundary 可消费 domain-neutral Harness contracts | import interfaces/infrastructure；在普通 application/service public contract 中暴露 Harness DTO；构造 concrete store/adapter |
| `infrastructure/research` | 实现 Research outbound ports、source/compiler/storage/RAG adapters | 依赖 Research application/services/workflows 或复制 domain rule |
| `framework/harness` | state、scheduler、gate registry、routing、transcript authority | Research/paper-specific DTO、fixture 或规则 |
| `framework/tool` | canonical tool model、risk/approval execution contract | business/infrastructure tool inventory ownership |

`infrastructure` 依赖 business-owned ports/domain DTO 是允许的 hexagonal adapter 方向，但必须由精确 architecture allowlist 表达。Blanket allowlist 不得扩展到 `business.research.application`、`services`、`workflows` 或 concrete parser/runtime implementation。

上表是仓库级依赖方向护栏，不等于本阶段承诺一次性迁移所有历史 interface。阶段 20 的强制 closure 范围是 RES-009 所列 Research 六入口，以及本阶段新增或修改的 interface 代码；其他既有 interface 若审计发现绕过 application service，必须先建立独立 finding、accountable requirement、OpenSpec owner 和 regression，再进入迁移，不得借本 PRD 无证据扩展范围。

本阶段不全面禁止 `business/research -> framework`。Research 可以依赖经过批准的 domain-neutral Harness contract；需要收敛的是 `rag_policy.py`、`paper_rag_session.py` 等普通 service/application 模块分散构造 Harness DTO/controller，以及 framework 反向出现 Research-specific fixture/rule。`build_paper_analysis_workflow_spec()` 是 production analysis 的外层 workflow contract，`RAGSessionSpec`/`BoundedRAGSessionController` 只能作为该 workflow step 的有界子会话，或作为显式 standalone ask scope；两者不得竞争同一外层 routing/publication authority。`ResearchSinglePaperRuntime` 的最终位置与职责必须在 `research-runtime-production-composition` design 中明确，不能靠 import 移动暗中改变。

### 5.4 Compatibility first

- 现有 endpoint path、SDK method、approval JSON schema、quality artifact key、checkpoint/event schema 和 artifact ref 不得静默破坏。
- 迁移必须采用 expand -> dual-read/adapter -> cutover -> contract window -> delete。
- Compatibility adapter 必须有 owner、删除条件和最长一个 release window；不得成为第二条永久运行路径。

每个 compatibility adapter 必须在对应 OpenSpec 的 `evidence.md` 登记 `surface`、`owner`、`introduced_release`、`expires_release`、`removal_condition`、`telemetry`、`evidence` 和 `kill_switch_retirement`。`introduced_release` 是首次包含 adapter 的发布，`expires_release` 最迟是其后的一个发布；若仓库尚未分配版本号，则使用目标 release id 并同时记录引入 commit。到期 adapter 必须删除或先通过新的 OpenSpec/PRD 决策显式续期，阶段级验收要求 registry `overdue=0`。

---

## 6. 目标架构与 canonical ownership

### 6.1 控制与运行路径

| 顺序 | Owner | 输入 | 输出/约束 |
| --- | --- | --- | --- |
| 1 | Interface composition + application service/use case | settings、actor、transport request | application request + concrete port graph；transport 不直达 executor/store |
| 2 | Source collection | normalized source request、shared fetch policy | canonical Source records + fetch lineage |
| 3 | Evidence assembly | Source records、Research document/chunks | bounded evidence set + source refs；缺口显式记录 |
| 4 | Harness PLAN/EXECUTE | workflow spec、state、budget、evidence refs | LLM/subagent 只返回 analysis candidate |
| 5 | Research report builder | verified-shape candidate、evidence refs | candidate report；不得自行发布或写 memory |
| 6 | Harness VERIFY | candidate report、deterministic gates | versioned gate results + verdict |
| 7 | Harness scheduler | verified verdict、explicit policy | replan/retry/repair/halt/complete；全程受预算约束 |
| 8 | Artifact/run/experience stores | accepted outputs、隔离的 candidate/diagnostic outputs、events、refs | accepted outputs 才能进入 canonical/published store 与 latest index；失败、halted 或待审批输出只能进入 quarantine namespace，且 publication 与 memory write 需要独立确定性授权 |

任何默认入口都必须保留 `source collection -> evidence -> agent analysis -> report -> quality gate -> artifacts/storage` 的顺序。降级路径可以缩减证据内容，但不能跳过 evidence lineage、deterministic gate 或 accepted-output publication 边界。

### 6.2 Ownership matrix

| Contract/能力 | Canonical owner | Adapter/consumer |
| --- | --- | --- |
| Harness gate registry/verdict | `framework/harness` | Research gates、Workflow declarations |
| Approval request/decision/status | `framework/workers/approval` | Tool wrapper、interfaces、LocalJson 及任何明确声明支持的 durable store |
| Tool risk decision | `framework/tool` policy/governance | framework/infrastructure/business registries |
| Harness production tool composition | 目标 owner `interfaces/composition` + `tool-governance-canonicalization`（planned） | `HarnessToolPort`/`MCPToolPort` production adapter、ToolRegistry 与 Source runtime provider；当前只有 Protocol/export/fake，`HarnessControlPlane` 尚未接入 production owner |
| Research production graph | `interfaces/composition/research.py`（完整 object graph、durable store 与入口切换已由 `12ed843a` 交付） | HTTP/MCP/CLI entry surfaces；configured graph 使用真实 runtime 与 durable store，缺失或无效配置保持 typed/sanitized fail-closed；六入口复用同一 production provider policy |
| Research domain/ports | `business/research` | infrastructure Research adapters |
| Source identity/canonical URL | `business/foundation/primitives/source_ref.py` | `infrastructure/external/sources/url_utils.py` 仅作无逻辑 adapter；normalization、tools、Research Source identity consumers |
| Source retry/rate-limit execution | `infrastructure/external/sources/fetch_policy.py` | business limiter port/decision DTO、`interfaces/services/source_runtime.py`、connectors/tools/health/Research arXiv |
| Source error taxonomy | `business/layers/signal/source_processing/error_taxonomy.py` | infrastructure taxonomy re-export、health、quality/operator projections |
| Source error construction | `infrastructure/external/sources/errors/factory.py` | 八个 connector；保留 connector-specific classification/diagnostics |
| Source DTO object mapping | `interfaces/services/source_mapping.py` | Source application/tool/interface projections；不得承担 persisted payload decode |
| SourceError serialized reader | `business/foundation/models/source_error_normalization.py` | artifact/event/checkpoint/PostgreSQL readers；只允许 exact adapter-to-contract import，不得依赖 business application/service 或复制 retry precedence |
| Analysis quality engine | `business/layers/analysis/quality` | production tools、eval、Research adapter |
| Workflow graph semantics | 目标新 owner `framework/specs/graph_semantics.py`（planned/new；纯函数/不可变 graph contract） | 该 leaf module 只依赖 stdlib 并定义 normalized node/edge inputs；`WorkflowSpec`/`EdgeSpec` 通过单一 spec adapter 投影，validation、compiler、dataflow、scheduler/runtime 消费同一结果。禁止 owner import sibling specs model、validation、compiler、runner 或 runtime，必须保留 edge kind |
| LLM budget（待 U10 验证） | 候选 owner `framework/llm/budget` | 只有同一 logical budget parity 证明重复后，Agent/Workflow 才降为领域 adapter；否则记录显式变体边界 |
| Conversation persistence record（待 U10 验证） | 候选 owner `framework/agent/messages/message.py` | 只有 message/compaction/cursor/checkpoint lifecycle 与 persistence parity 证明重叠后，infrastructure 才只保留 mapper/backend lifecycle |
| Memory record/document contract（待 U10 验证） | 候选 owner `framework/memory/models/record.py` + `framework/memory/indexing/document.py` | 只有 Local/Vector/Qdrant input/output 与 lifecycle overlap 证据成立后收敛；backend `VectorDocument` 不自动视为重复 |
| Skill experience store/provenance | `framework/harness/skills/evolution` | Research memory/experience adapter |

### 6.3 Requirement kind 与完成证据

每个 requirement 只有一个 accountable OpenSpec change，并且必须在该 change 内指定一个 accountable task；一个 task 可以承接同一原子交付边界内的多个 requirement ID，但单个 requirement ID 不得同时由多个 task/change 声明完成。第 17.2 节只负责 change-level routing；新切片在开始 implementation 前，已进入 implementation 但早于本 PRD 的 active change 在下一项 open task 勾选完成前，必须在 `tasks.md`/`evidence.md` 补齐 `requirement ID -> task -> test/evidence -> implementation commit` 明细。其他 task/change 可以是 dependency、consumer 或 integration evidence provider，但不取得该 requirement 的完成权。完成证据按 requirement 的主导类型判定：

| Kind | Requirement IDs | 必须完成的证据 |
| --- | --- | --- |
| `behavioral` | HAR-001..005、HAR-008..009；RES-001..002、RES-005..008、RES-011；TOOL-002..005；SRC-002..004、SRC-006；QLT-001、QLT-004；WF-001..002 | deterministic failing regression + passing acceptance/contract test + runtime evidence |
| `contract` | HAR-006..007；RES-003..004、RES-009..010；TOOL-001、TOOL-006..007；SRC-001、SRC-005；QLT-003；WF-003..004 | schema/AST/dependency or cross-implementation conformance test + compatibility evidence |
| `migration` | QLT-002、WF-007 | versioned decision/migration record、golden fixtures、validator；能确定性测试的部分仍必须有 passing test |
| `retirement` | QLT-005、WF-005..006、WF-008 | import/export/dynamic-entry/consumer/persistence/replay audit、expiry 与 deletion evidence；不得用 prose-only waiver |

---

## 7. 详细需求 A：Harness deterministic VERIFY authority

### 7.1 Requirements

| ID | Requirement |
| --- | --- |
| HAR-001 | `HarnessWorkerResult` 不得携带可直接解释为 route、quality verdict、approval、memory write 或 publication decision 的字段。保留模型自评分时必须命名为 observation，并且 gate/controller 不直接采用。 |
| HAR-002 | `HarnessStepSpec.quality_gate` 必须解析到 deterministic gate registry；未知、重复、版本不兼容或缺少依赖的 gate 在 run start 前 fail-closed。 |
| HAR-003 | 每个 step 只执行其声明 gate 加全局 mandatory gates；不得用一个不区分 step 的 gate 列表替代声明契约。 |
| HAR-004 | `HarnessQualityVerdict` 只能从 gate result aggregation 生成；默认 `passed=True` 仅允许明确声明“无 quality gate”的 framework utility step。 |
| HAR-005 | Harness 必须按有界 `PLAN -> EXECUTE -> VERIFY` 状态机推进。Gate failure 只能触发 spec/policy 允许的 retry、replan、repair、halt 或 fail；`max_replans`、`max_turns` 与 retry budget 在边界值耗尽后必须形成稳定 terminal state，且不得再调用 worker 或 gate。 |
| HAR-006 | Durable transcript/event log 必须记录每次 phase transition、attempt/retry/replan counter、gate id/version、input refs/hash、结果、失败原因、聚合 verdict、scheduler decision 和 terminal reason。事件必须具有稳定 identity 与单调顺序；重复投递不得重复推进状态，缺失或乱序事件必须 fail-closed，replay 必须重建相同 state、counter 与 decision。 |
| HAR-007 | Research workflow 中声明的 gate 必须逐一映射；不存在的历史 gate name 必须删除或实现，不能仅作为 metadata 保留。 |
| HAR-008 | Worker 返回的 tool authorization、memory-write、publication 或 skill-promotion 建议只能是 candidate observation；Harness 必须丢弃或显式拒绝可执行 decision 字段，并分别调用 canonical policy/gate。 |
| HAR-009 | Report、memory 和 production artifact 的最终写入只能发生在 deterministic gate/authorization 成功之后；失败、halted 或待审批 run 只能写隔离的 candidate/diagnostic artifact，不得进入 published/latest index。 |

### 7.2 Acceptance

- 任何 `worker_type=llm|subagent` 的自报 score 都不能单独改变 route。
- `quality_gate="DefinitelyMissingGate"` 在执行 worker 前失败。
- Research paper-analysis workflow 的每个 gate name 都有 registry identity 和 committed execution test。
- `max_turns`、`max_replans` 与 retry budget 分别覆盖 `limit-1`、`limit`、`limit+1` 边界；耗尽后 run 进入唯一 terminal state，后续 worker/gate 调用数为 `0`。
- 正常、gate failure、retry、replan、repair 与 halt 路径均记录完整 `PLAN -> EXECUTE -> VERIFY` transition 序列；事件 identity/sequence 无缺失、重复或倒序。
- Replay 使用已记录 phase/gate/decision events 重建相同 state、counter 与 scheduler decision，不重新调用 LLM 或以当前默认值替换历史 verdict；重复事件幂等，缺失或乱序事件 fail-closed。
- Worker 即使返回 `approved=true`、`write_memory=true` 或 `publish=true`，也不能增加 tool side effect、memory record 或 published artifact；拒绝原因写入 transcript。
- Worker 即使伪造 `promote_skill=true`、production version 或 active package ref，也不能修改 active skill package、promotion record 或 release index；普通 run 的 active-skill mutation/promotion count 为 `0`，candidate 与拒绝原因进入 transcript，只有 Harness 控制的 held-out evaluation/promotion workflow 可以激活版本。
- Gate failure、approval pending、budget halt 三种终态可以持久化 quarantine candidate/diagnostic artifact，但 published/latest index 必须不可见；accepted run 才能原子写入 canonical/published store，并有 contract test 验证两类 namespace 的 read/write 隔离。

---

## 8. 详细需求 B：Research production composition 与边界

### 8.1 Requirements

| ID | Requirement |
| --- | --- |
| RES-001 | 复用 active `research-runtime-production-composition`，让 configured HTTP/MCP/CLI 默认入口共享 `ResearchApplicationService -> AnalyzePaperUseCase -> ResearchSinglePaperRuntime` production factory。 |
| RES-002 | Configured graph 不得包含 `_UnconfiguredAnalyzeUseCase`、Research fake、`FakeArtifactPort` 或 production `InMemoryResearchRunStore`；缺配置时返回 typed/sanitized unavailable service。 |
| RES-003 | 普通 `business/research/application` 与 `services` 的 public contract 只暴露 Research request/result/ports，不分散构造 `RAGSessionSpec`、`BoundedRAGSessionController` 或 concrete store；`business/research/workflows` 拥有 canonical 外层 `HarnessWorkflowSpec`，production analysis 必须把它传入 `HarnessRunSpec`。指定 runtime boundary 可消费 domain-neutral Harness control-plane contract；bounded RAG session 只能是 workflow step 的子会话或显式 standalone ask scope，不能成为第二个外层 controller。 |
| RES-004 | `infrastructure/research` 只依赖获批的 `business.research.domain` / `business.research.ports` contract；禁止依赖 application/services/workflows 和 concrete business runtime/parser implementation。 |
| RES-005 | `/ask` 与 `/rag-ask` 统一由注入的 Research application factory 管理；以显式 mode 保留 summary projection 与 chunk-RAG 差异，不保留 router-owned singleton。 |
| RES-006 | API actor 的 `tenant_id/user_id/memory_namespace` 必须进入 RAG retrieval、visibility、memory 和 transcript；tenant-aware 数据不允许在 tenant 缺失时静默全量放行。 |
| RES-007 | `SkillExperience` 必须先通过 Harness-controlled store 持久化，成功后才返回 ref；package hash 来自真实 released package manifest，ref 在 service/process 重建后仍可查询。普通 Research run 不得触发 promotion。 |
| RES-008 | Analysis、reader、ask、trace 和 artifact refs 在 service/process 重建后仍可查询。 |
| RES-009 | HTTP、MCP 和 CLI entry surfaces 只调用 `ResearchApplicationService` 或明确的 application use case；禁止 router/server/adapter 直接访问 Harness executor、repository、run store 或 artifact store。Worker 不属于本 change 的六入口 parity，若未来暴露 Research 能力必须遵守同一 architecture rule。 |
| RES-010 | MCP server 入站接口与 ToolRuntime 出站 MCP adapter 使用独立 composition/port；入站 server 不得把请求回送到 outbound adapter 形成隐式递归或共享 transport-global request state。 |
| RES-011 | Production factory 可以 process-scoped cache 昂贵 client/store，但必须有显式 lifecycle/reset hook；request/run state 只能位于 run-scoped object 或 context-local binding，禁止无生命周期的模块级 mutable singleton。 |

### 8.2 Architecture rule

`tests/architecture/test_infrastructure_boundary.py` 必须从“全部禁止”收敛为可解释规则：Research adapter 可以 import 稳定 port/domain DTO，但不得通过宽泛 `business.*` allowlist 掩盖 application/service/runtime 依赖。现有 7 个 violation 必须逐项迁移或收窄，不允许只添加目录级例外使 smoke 变绿。Architecture suite 还必须覆盖 Research 六入口及本阶段新增/修改 interface 的 interface -> application 调用方向、MCP inbound/outbound 隔离、禁止 import cycle 和禁止未登记模块级 mutable runtime state。

### 8.3 Acceptance

- 默认 configured API 真实执行一次 recorded-transport Research analysis，并在新 service instance 中读取 analysis/trace。
- 全文编译必须保持 source identity 连续：`ResearchDocument.source_hash` 与 `lineage.source_hash` 必须等于已接受的 `PaperSourceRecord.source_hash`；parser 计算的内容 hash、LaTeX package checksum 与 PDF checksum 必须写入独立 metadata 字段，不能覆盖 source identity。LaTeX、PDF 与 abstract fallback 三条路径都必须通过真实 `ResearchDocumentSchemaGate` 回归。
- Recorded production analysis run 必须记录 `research.paper_analysis` workflow id、version/checksum、`PLAN -> EXECUTE -> VERIFY` phase transition 和声明 gate identity；仅验证静态 spec shape 不算通过。嵌入 analysis 的 bounded RAG session 必须记录 parent run/workflow/step identity，standalone ask 必须使用显式独立 session scope。
- 六个 entry/adapter surfaces 使用同一 factory implementation/version 与 object-graph contract：HTTP Research route、HTTP MCP route、local `MCPApplicationService` call、stdio MCP loop、CLI direct MCP commands（不把 `serve-stdio` 重复计数）以及 adapter-only `NewsMCPServerAdapter` contract。同一进程复用受管 client/store，跨进程通过 durable store 读取同一 run；parity 不要求六者拥有相同 transport loop。
- `/ask` 与 `/rag-ask` 都通过注入的 application factory；route-level tests 覆盖显式 mode/alias、actor/tenant propagation、并发隔离和两种 projection 的预期差异。
- 新建 service/process 后，analysis、reader、ask、trace 和 artifact refs 均可按既有 contract 查询，不依赖旧进程内对象。
- Factory lifecycle tests 证明 process-scoped client/store 可受控复用和 reset/close，request/run state 不跨请求、tenant 或测试泄漏。
- 返回的每个 `skill_experience_ref` 都可查询；metadata 不出现 `fake` hash。
- `business/research` 继续不依赖 legacy `business/boards/paper_radar`、interfaces 或 infrastructure。
- AST/import graph 证明六个 entry/adapter surfaces 不直接 import/调用 Harness executor 或 concrete store，且 MCP inbound/outbound dependency graph 无环。

---

## 9. 详细需求 C：Tool approval 与 risk policy 收敛

### 9.1 Requirements

| ID | Requirement |
| --- | --- |
| TOOL-001 | 保留 tool-specific `ToolApprovalRequest`，删除重复 generic approval DTO；转换必须返回 `framework.workers.approval.ApprovalRequest`。 |
| TOOL-002 | InMemory、LocalJson 及本切片明确声明支持的任何新增 store，对 pending、decision、重复决定、expiry、secret rejection 使用同一语义；不存在的 Postgres approval adapter 不作为隐式范围。 |
| TOOL-003 | 定义一个以 `ToolDefinition` 为输入并返回 `risk_level`、`requires_approval` 与 reason codes 的 canonical risk decision；结构化信号按最高风险合并，name list 只能作为只升不降的 legacy/default fallback。 |
| TOOL-004 | Framework registry 只拥有 base tools；infrastructure/business 追加各自 definitions。每个 built-in tool name 只有一个 registration owner，重复注册 fail-closed。 |
| TOOL-005 | Catalog、schema export、batch executor、ToolExecutor、inspection 和 Harness tool gate 必须调用同一 risk decision；framework/infrastructure/business inventory 不得各自重写 filter/classifier。 |
| TOOL-006 | `business/tools.py` 不再选择 concrete infrastructure connectors；concrete binding 移到 interface composition。 |
| TOOL-007 | `tool-governance-canonicalization` 必须消费 `framework-runtime-safety-hardening` 产出的唯一 registry/composition contract，不得建立第二套 registration path；unique registration 与 risk/approval semantic 分别由各自 change 验收。 |

Risk signal 冲突必须按下表 fail-closed；`is_dangerous=false` 仅表示没有该项升级信号，不是 safe override。为保持历史/custom definition 可读，未知 `side_effect` 统一判为 `medium + requires_approval` 并记录 `unknown_side_effect` reason code，不能静默降为 read-only。

| Signal | Risk floor | Approval rule |
| --- | --- | --- |
| `is_dangerous=true`、`side_effect=destructive|dangerous` 或 dangerous-name fallback | `critical` | required |
| `side_effect=publishing|writes_external_state|external_write|network_write` | `high` | required |
| 其他非 `none/read_only` side effect、未知 side effect、`requires_approval=true` 或存在 `required_secret_names` | `medium` | side effect/unknown/explicit approval 时 required；仅 secret dependency 不单独强制人工审批 |
| `side_effect=none|read_only` 且没有更高信号 | `low` | not required |

多个信号同时存在时取最高 `risk_level`，approval 使用逻辑 OR；任何低风险字段、`false` 默认值或 name fallback 都不能降低结构化信号已经确定的 risk/approval 结果。

### 9.2 Acceptance

- `to_worker_approval_request()` 的类型 identity、serialization 和 decision lifecycle 在所有 store contract tests 中一致。
- 重复 decision 稳定失败，失败不覆盖原 reviewer、time 或 modifications。
- 使用同一 fake clock 和 request fixture 时，InMemory、LocalJson 及本切片新增 store 对 expiry 产生相同 terminal status/error code；过期后 decision 失败且不改写原 record。payload、metadata 或 modifications 含 secret-like key 时必须在持久化前以同一 typed error 拒绝，store record count 保持 `0`，diagnostic 不含 secret value。
- 同一工具全集在所有入口的 risk classification 完全一致。
- `mcp.*`、`source.fetch_url`、`local_json.save`、`qdrant.upsert`、`artifact.write`、`postgres.query` 有明确 golden decisions。
- Risk golden matrix 覆盖 structured/name/side-effect/approval/secret 信号的单项与冲突组合、未知 side effect 和 `is_dangerous=false`；所有入口的 `risk_level`、`requires_approval` 与 reason codes 完全一致且只升不降。
- `ToolExecutor` 在 approval record durable 前不执行 side effect。

---

## 10. 详细需求 D：Source runtime policy 收敛

### 10.1 Requirements

| ID | Requirement |
| --- | --- |
| SRC-001 | `business/foundation/primitives/source_ref.py` 是 canonical URL identity contract，锁定 scheme/host/port/path/trailing slash/query key/tracking key/relative URL 行为；signal-layer 算法副本删除，infrastructure 只保留无逻辑 adapter。 |
| SRC-002 | Default connector、source tool、health probe 和 runtime assembly 对同一 domain 使用 `infrastructure/external/sources/fetch_policy.py` 创建的共享 limiter ledger；API、MCP、worker、CLI 与 Source-tool entry 按 process/command lifetime 复用稳定 composition，不能按 connector class、request 或入口拆配额。Research arXiv package/PDF 必须注入同一 provider/ledger；Harness Source-tool capability 必须绑定唯一 production registry/ToolPort owner，或通过独立 OpenSpec 明确声明当前不支持，禁止为完成 task 创建第二 registry。 |
| SRC-003 | Retry decision 仅由 `infrastructure/external/sources/fetch_policy.py` 实现，明确 HTTP status、timeout、URL/config error、unknown error 和 exhausted budget 语义。 |
| SRC-004 | Error taxonomy 仅由 `business/layers/signal/source_processing/error_taxonomy.py` 实现；connector-specific keyword 只能作为显式扩展输入，不复制整套 classifier。 |
| SRC-005 | Business/infrastructure live DTO 可以不同，但 object projection 必须通过 `interfaces/services/source_mapping.py`；persisted `SourceError` payload 由 `business/foundation/models/source_error_normalization.py` 的受限 codec contract 解码。两条路径都必须保留 `request_ref`、`response_ref`、`occurred_at`、timezone、metadata 与 retry semantics，且不得互相复制职责。公开 `RawSourceItem` payload 必须保留全部 17 个字段、lineage、`raw_artifact_ref`、`parse_artifact_ref`、nested metadata，并统一输出 UTC `Z` 时间。 |
| SRC-006 | 八个 connector 的重复 `_source_error()` 收敛到 `infrastructure/external/sources/errors/factory.py`，同时保留 connector-specific classification/diagnostics。 |

### 10.2 Acceptance

- URL golden corpus 在 connector、SourceRef、signal pipeline 和 tool path 输出一致。
- 同域跨 RSS/HTML/tool/health 的第 N+1 次请求在 network fetch 前被统一 rate-limit。
- API/MCP/worker/CLI/Source-tool 连续调用保留同一 quota state；Research arXiv 使用同一 ledger；Harness Source-tool 只有一个 production composition owner，或存在经批准的 explicit unsupported decision。
- Retry matrix 对 HTTP 4xx/5xx、timeout、URLError、ValueError 和 unknown error 有唯一预期。
- SourceError 经 live object mapping 后没有字段、时区或 metadata 丢失；历史 persisted payload 通过 canonical codec/real reader 解码并保持原 instant、refs 与 retry semantics。
- 同一 `RawSourceItem` 经 connector、application service、API/MCP、worker、CLI、Source tool 与 connector tool 投影后，17 个公开字段、lineage、artifact refs、nested metadata 和 UTC `Z` 完全一致；任何入口不得手写缩减 serializer。
- Source DTO enum 差异通过支持矩阵记录，不通过强制继承或字段并集掩盖。

---

## 11. 详细需求 E：Analysis quality 单一生产 owner

### 11.1 Decision

`business/layers/analysis/quality` 成为共享 citation/support/scoring/editor 规则的 canonical engine。现有 `quality_records.py` 在迁移窗口内只保留 payload compatibility adapter，不再拥有独立算法；Research 保留 Research-specific readiness、paper-card、taxonomy 和 evidence-shape gates，但共享 citation/support 规则必须委托 canonical engine。

### 11.2 Requirements

| ID | Requirement |
| --- | --- |
| QLT-001 | Production `quality.*` tools、eval dataset 和通用 report quality service 使用同一 canonical engine/version。 |
| QLT-002 | 迁移前用同一 golden corpus 记录旧/新差异；每项差异必须标记为 bug fix、intentional stricter rule 或 compatibility requirement。 |
| QLT-003 | 旧 payload keys、artifact types、event fields 和 persistence projection 通过 mapper 保持兼容。 |
| QLT-004 | Research-specific gate 不能复制 canonical claim/citation/support algorithm，只添加领域特有约束。 |
| QLT-005 | `quality_records.py` compatibility window 最长一个 release；包外 consumer 验证完成后删除。 |

QLT-002 的差异分类由 Analysis Quality domain owner 与 Architecture owner 共同批准并记录到该 change 的 `evidence.md`。每条 decision record 至少包含 corpus case id、旧/新结果、`bug_fix|intentional_stricter|compatibility_required` 分类、公共/持久化兼容影响、批准者和日期；未分类差异不得进入 production cutover。

### 11.3 Acceptance

- Production tools 与 eval 使用相同 engine identity。
- Golden corpus 中所有判定差异都有批准的 decision record，没有“两个都算对”。
- 既有 report quality payload、artifact 和 projection round-trip 不变。
- 删除 compatibility adapter 后，全仓无旧算法 import；公共 API 如需保留，只保留薄 serialization facade。

---

## 12. 详细需求 F：Workflow/framework contracts 与 legacy 收敛

### 12.1 Requirements

| ID | Requirement |
| --- | --- |
| WF-001 | 新建 stdlib-only 的纯 graph semantics owner `framework/specs/graph_semantics.py`，以 normalized node/edge value inputs 工作，由唯一 spec adapter 连接 `WorkflowSpec`/`EdgeSpec`，再供 Spec validation、compiler、dataflow、cycle detection 和 runtime 共同消费；fallback edge 是正式 graph edge并保留 edge kind。当前 `framework/workflow/compiler/graph_builder.py` 只作为限时 compatibility facade 或删除，不能让 specs 反向依赖会 import `framework.specs` 的 compiler。 |
| WF-002 | 先完成 U10 logical budget parity：比较 router、Agent、Workflow 的输入、reserve/record/cost rounding、拒绝和生命周期。只有行为重叠时才将 token/cost/call budget 收敛到 `framework/llm/budget`；tool/wall-time 或生命周期不同的变体继续由原领域拥有。 |
| WF-003 | 先完成 U10 conversation contract matrix：比较 message/compaction/cursor/checkpoint 的生产调用、序列化、事务与恢复语义。只有重叠字段和状态机通过 parity 后，才收敛到 `framework/agent/messages/message.py` 并让 LocalJson/Postgres 使用显式 mapper；否则记录不可合并差异。 |
| WF-004 | 先完成 U10 memory record/document matrix：比较 ingestion、query、Local/Vector/Qdrant payload、index identity 与 lifecycle。只有 domain contract 重叠时才由 `framework/memory/models/record.py` 与 `framework/memory/indexing/document.py` 统一；backend-specific DTO 与事务语义保留。 |
| WF-005 | 新 Harness-managed code 禁止依赖 legacy Agent/Workflow control-plane result；旧 exports 冻结，不新增调用方。 |
| WF-006 | 旧 WorkflowRunner/Agent subagent/budget 的删除必须先完成包外 import、动态入口、checkpoint/replay 和 persisted payload compatibility 审计。 |
| WF-007 | Framework fake 必须 domain-neutral；paper/reader-repair-specific fixture 移到 Research tests。 |
| WF-008 | 私有 `_build_*`/`_legacy_build_*`、connector timeout/taxonomy wrapper 和薄 test-only facade 只有在 owner-local child change 取得 production/import/export/dynamic-entry/persistence/replay 五类证据后，才能标记不可达并删除；必须先有替代回归覆盖。 |

### 12.2 Acceptance

- fallback-only terminal workflow 可 strict compile 并按同一 graph 执行；fallback dataflow/cycle/max-visits 有测试。
- AST/import-cycle test 证明 graph semantics owner 不依赖 compiler/runner/runtime，且不存在 `framework.specs -> framework.workflow.compiler -> framework.specs` 环。
- U10 先产出 budget、conversation、memory 三张 A/B contract matrix；确认重叠的 case 才要求 canonical owner parity，确认不重叠的 case 记录输入输出、lifecycle 与保留 owner。
- 对确认需要收敛的 contract，router/Agent/Workflow budget parity、AgentRunner -> LocalJson/Postgres conversation round-trip、MemoryIngestion -> vector store round-trip 全部通过；未确认项不以新增 generic adapter 伪造统一。
- 新生产代码对 legacy control-plane modules 的 import 数为 `0`。
- 删除清单中每个 public symbol 都附外部 consumer/replay evidence；无法确认的项保持 deprecated，不宣称安全删除。

---

## 13. 公共 API、数据与兼容矩阵

| Surface | 本阶段策略 | 允许变化 | 禁止变化 |
| --- | --- | --- | --- |
| Research HTTP/MCP | 保留现有 route/tool 名，替换默认 factory | unavailable error 可增加稳定 capability details | 成功 response envelope、analysis/reader/trace key 静默变化 |
| `/ask`/`/rag-ask` | 统一 service owner，保留显式 mode/alias | 增加 deprecation metadata、actor propagation | router singleton 和无 tenant filter 继续作为默认 |
| Approval store v1 | 保留 JSON fields 和 id | 修复 runtime type、validation、idempotency | 重写已有 approval id/status 或泄漏 secret |
| SourceError | Live object mapper 与 persisted serialized reader 职责分离，完整字段 round-trip | 恢复此前丢失字段、增加受限 codec validation | 改变 error_type/retryable 历史语义而无 migration，或让 persistence reader 复制 interface mapper |
| Source public item payload | 锁定 `RawSourceItem` 17 字段、lineage、artifact refs、nested metadata 与 UTC `Z` | 通过 additive/versioned field 扩展 | 任一 API/MCP/worker/CLI/tool 入口静默删字段、改时区或使用缩减 serializer |
| Quality artifacts | canonical engine + compatibility mapper | 新增 engine version/reason codes | 删除已有 artifact keys、projection fields |
| Workflow checkpoint/events | 消费阶段 19 contract | graph semantics 修正 | 私自改 event/checkpoint schema 或 replay ordering |
| Conversation/vector data | mapper/port contract | 增加 validation | 无迁移改 persisted JSON/SQL/Qdrant payload |
| Skill experience | ref 变为可查询、hash 真实 | 增加 manifest/release metadata | 普通 run 自动 promotion |

---

## 14. OpenSpec 映射与 change 边界

### 14.1 复用 active 与 archived changes

| Existing change | 本 PRD 使用范围 | 禁止扩展 |
| --- | --- | --- |
| `harness-deterministic-gate-enforcement`（ARCHIVED） | HAR-001..007 的 gate binding、worker score isolation、gate-derived verdict、bounded scheduler 与 replay 基线；实现 `017a227e`。HAR-005/006 的强化验收先组合复用该 archived regression、canonical `harness-runtime` spec 与 `durable-event-runtime` 的 ordered/idempotent/fail-closed replay evidence | 不重开 archived tasks；若 `limit-1/limit/limit+1` 或 phase-event duplicate/missing/out-of-order 矩阵仍有缺口，必须新建 modified-requirement change 并更新本表的单一 accountable owner，不得把新增工作伪记为 archived completion |
| `source-policy-contract-convergence`（ACTIVE） | SRC-001..006 的 URL identity、fetch policy、taxonomy、error factory、object mapper、serialized reader、shared composition 与 compatibility cutover。Core、API/MCP/worker/CLI entry binding、Research arXiv binding、Harness Source-tool capability 四个 gate 分开记录；只有相关 gate 均有 evidence 后才能勾选对应任务 | implementation `372027ac` 已提交并有 `evidence.md`；当前状态与开放任务只引用第 1.1 节。不把 Tool authorization、Research parser/RAG 或 generic framework utils 纳入 Source change；不得为提前勾选 task 新造第二个 Research factory、Harness registry、Source runtime 或 limiter |
| `research-runtime-production-composition`（ACTIVE / UNARCHIVED） | RES-001..006、RES-008..011 的 production factory、adapters、durable run store、六入口/adapter parity、外层 workflow/内层 RAG session ownership、`/rag-ask` lifecycle/actor propagation、interface/MCP adapter boundary 和 lifecycle；implementation `12ed843a` 已交付完整 object graph、durable store、actor scope、entrypoint、recorded transport、shared resources、parent/child replay 和必要的 durable dependency closure | 当前数字与开放边界只以第 1.1 节和该 change `evidence.md` 为准。不以 task completion 宣称 live provider 或阶段 20 ready；不顺手重写 Harness quality、Tool policy、Source 全局 policy，只注入 Source change 已验证的 provider/ledger contract |
| `framework-runtime-safety-hardening` | TOOL-004 的 unique built-in registration、composition safety；继续完成其 attempt/lease/error scope | 不在无 proposal 更新时加入 approval/risk model、quality engine 或 Workflow graph 迁移 |
| `durable-event-runtime` | HAR-006、RES-008 所消费的 durable transcript/event/replay contract | 本 PRD 不修改 canonical event、outbox/inbox、sequence 或 replay engine |

### 14.2 建议新增 changes

| 顺序 | Change | Requirements | 说明 |
| --- | --- | --- | --- |
| 1 | `harness-side-effect-authority-closure` | HAR-008..009 | 先提交越权字段与 publication ordering contract probes；仅在 probe 失败时修复 production，不重造 gate/state machine |
| 2 | `tool-governance-canonicalization` | TOOL-001..003、005..007 | P1/P2；消费 `framework-runtime-safety-hardening` 已验收的 TOOL-004 unique registration contract，不并行修改 registry ownership |
| 3 | Conditional `harness-source-tool-composition` | SRC-002 Harness integration evidence | 仅当 U2 确认 Harness 应支持 Source tools 时创建；接入唯一 ToolRegistry/ToolPort 与同一 Source provider。若能力明确不支持，则在 Source change 中记录经批准的 capability decision，不创建空 registry/fake path；SRC-002 仍由 Source change accountable |
| 4 | `analysis-quality-contract-convergence` | QLT-001..005 | 先 parity，后 production cutover，再删旧算法 |
| 5 | `workflow-canonical-graph-semantics` | WF-001 | 先建立不依赖 compiler/runtime 的 pure specs graph owner，再迁移 fallback/reachability/dataflow/cycle consumers；保持 serialization/replay version compatibility并增加 import-cycle gate |
| 6 | `research-experience-memory-provenance` | RES-007 | 独立于 production composition，修改 `harness-skill-evolution` experience/store/provenance contract |
| 7 | Conditional `framework-budget-contract-convergence` | WF-002 | U10 parity 证明同一 logical budget 行为重叠后才创建；否则记录保留决策，不新建 generic owner |
| 8 | Conditional `framework-conversation-contract-convergence` | WF-003 | U10 证明 message/compaction/cursor/checkpoint 与 LocalJson/Postgres contract 重叠后才创建 |
| 9 | Conditional `framework-memory-document-contract-convergence` | WF-004 | U10 证明 memory record/document 与 Local/Vector/Qdrant domain contract 重叠后才创建；backend lifecycle 不强并 |
| 10 | `framework-legacy-inventory-and-freeze` | WF-005..006 | 建立 export/dynamic/replay/consumer inventory、冻结新增调用方并定义删除门，不在该 change 跨域删除实现 |
| 11 | `framework-fixture-domain-boundary` | WF-007 | 只迁移 domain-specific framework fake/fixture，保持生产 contract 不变 |
| 12 | owner-local `*-legacy-retirement` child changes | WF-008 | Analysis、Source、Workflow/Agent、Research/test facade 分 owning area 提案、验收和删除；禁止一个 commit 跨域清场 |

### 14.3 Completed changes 的处理

`tool-approval-request-store`、`tool-dangerous-approval-policy`、`source-shared-rate-limiter` 和 `workflow-failure-policy-routing` 当前显示为 complete，但 live implementation 已出现回归或未覆盖场景。实施前必须：

1. 确认其 spec 是否已归档进入 canonical `openspec/specs`。
2. 未归档时先按仓库流程归档，不直接在 completed tasks 上追加工作。
3. 新 change 使用 modified requirement 或新 scenario 表达回归修复。
4. 在 requirements -> tasks -> tests 矩阵中引用原 requirement，说明是 regression、scope extension 还是 ownership correction。

---

## 15. 交付阶段、依赖与 commit 边界

| 阶段 | 交付内容 | 依赖 | 合并门禁 |
| --- | --- | --- | --- |
| P0（按 slice 持续） | 每个切片在自身修复前本地运行对应 failing regression、把 red 命令与失败 oracle 记录到 OpenSpec `evidence.md`，并冻结受影响 public contract snapshot | 无 | 每个新切片至少一条可复现的修复前失败证据；不合并 red commit；已归档切片保持 regression 常绿 |
| P1A（已完成基线） | Harness gate authority HAR-001..007 | P0；阶段 19 gate-event schema 稳定 | 已归档 change 的 focused、deterministic replay、architecture、smoke 保持常绿 |
| P1A2 | Harness authorization/memory/publication side-effect authority | P1A | forged decision fields、publication ordering、durable transcript、smoke |
| P1B | Approval canonical model、tool risk decision | P0；framework safety unique registration 完成 | Tool/store contract、全工具分类矩阵、smoke |
| P1C | Workflow canonical graph semantics | P0 | validator/compiler/runtime parity、serialization/replay compatibility |
| P2A-core（实施中） | Source URL/retry/rate/taxonomy、object mapper、serialized reader 与通用 composition 收敛 | P0 | Source contract matrix、public payload parity、shared quota、object/persistence round-trip；独立记录 core evidence，不提前勾选跨 owner tasks |
| P2A-entry | API、MCP、worker、CLI 与 Source-tool service 绑定稳定 Source composition | P2A-core | process/command lifetime 连续调用保留 quota state；无 per-request runtime 重建 |
| P2A-Research | 将同一 Source provider/ledger 注入默认 Research arXiv package/PDF composition，完成 task 3.7/3.10 的 Research 部分 | P2A-core；P3 Research factory 可构造 | recorded no-network typed denial、连续调用 quota state、无第二 Source runtime/ledger |
| P2A-Harness | 为 Harness Source-tool capability 绑定唯一 production ToolRegistry/ToolPort owner，或记录 explicit unsupported decision | P2A-core；P1B Tool governance；U2 决策 | production object graph/recorded run 证明同一 provider，或 capability contract 明确不可用；禁止 fake/空 registry。Source task 3.7 在该 gate 前不得完成 |
| P2B | Quality parity、canonical cutover、compat adapter | P1A/P1A2 | Golden decision review、artifact/persistence compatibility |
| P3 | Research production composition 完成；boundary、outer-workflow/inner-RAG-session ownership、ask、tenant、durability 和 experience 分批收敛 | P1A/P1A2/P1B/P2A-core；active Research change；P2A-Research 与 factory cutover 同批验收；`research-experience-memory-provenance` 完成后才验收 experience | HTTP/MCP/CLI parity、recorded workflow/session identity、restart/concurrency、no fake graph、shared Source ledger、experience lookup |
| P4 | 先验证 Budget、conversation、memory contract 是否真实重叠，再按确认结果分切片收敛或保留；legacy inventory/freeze 与 owner-local delete | P1-P3；U10；与 durable event 文件冲突解除 | A/B contract matrix；每个 port/backend 独立 contract；external import/replay audit；删除 commit 不跨 owning area |
| P5 | 全量回归、迁移/回滚演练、删除 compatibility window 到期项 | P1-P4 | mandatory smoke、strict OpenSpec、diff check、release evidence |

P1A2、P1B、P1C 可以在 file ownership 不冲突时并行；P2A-core 与 P2B 可以并行。P2A-entry 由 Source change 自身闭环；Research adapter/factory 在 P2A-core contract 稳定后即可推进，不等待 Source change 整体 complete；P2A-Research 与 P3 factory cutover 是一个共享验收门，双方不得互相声明为前置完成条件。P2A-Harness 独立于 Research gate，但会阻断 Source task 3.7 和 Source change overall completion。P3 final 仍须等待 Harness authority、Tool governance 和 Source core contract 稳定。P4 的 budget、conversation、memory changes 先共享 U10 evidence gate，确认后的 child changes 互不作为默认前置；若任一切片触碰 event/checkpoint 文件，必须等待 `durable-event-runtime` 对相同文件的 owner 明确后再实施。

每个 change 按 OpenSpec/spec -> regression + implementation -> migration/cutover -> deletion/docs 的逻辑顺序交付；只有在每个中间提交都通过其范围门禁时才拆成多个提交。修复前 red 状态只保存在本地运行记录或临时分支及 `evidence.md`，不得进入可合并历史；regression 与根因修复可以在同一个 green implementation commit 中提交。禁止用一个提交同时完成跨 Tool、Source、Quality、Research、Workflow 的大规模移动。

---

## 16. 文件级影响矩阵

### 16.1 必须修改或明确 owner

| Area | 代表文件 | 目标变化 |
| --- | --- | --- |
| Harness VERIFY | `framework/harness/control_plane/harness.py`、`scheduler.py`、`routing.py`、`workflow/step.py` | named gate registry、gate-derived verdict、worker observation 隔离、durable gate identity |
| Research composition | `interfaces/api/app.py`、`interfaces/services/research_service.py`、`interfaces/services/mcp_service.py`、`interfaces/api/routers/research.py` | 统一 production factory、durable store、移除 route singleton、actor propagation，并注入 Source core 已验证的 provider/ledger |
| Research boundary | `business/research/workflows/paper_analysis_workflow.py`、`services/rag_policy.py`、`application/paper_rag_session.py`、`application/single_paper_runtime.py`、`infrastructure/research/*` | 明确 canonical 外层 workflow 与 bounded RAG 子会话、designated runtime/adapter boundary、精确 port/DTO imports、experience store/provenance |
| Tool governance | `framework/tool/governance/approval.py`、`framework/workers/approval/model.py`、`framework/tool/models/policy.py`、framework/infra/business catalogs | canonical approval DTO 与 risk decision，registry 只追加 inventory |
| Source policy | business Source normalization/runtime/health、`infrastructure/external/sources/fetch_policy.py`、`interfaces/services/source_mapping.py`、`business/foundation/models/source_error_normalization.py`、Harness/Research composition boundaries | URL/retry/taxonomy/limiter/object-mapper/serialized-reader 单一 owner；entry、Research、Harness integration gate 独立；public `RawSourceItem` payload 不丢字段 |
| Quality | `business/layers/analysis/quality_records.py`、`analysis/quality/*`、`analysis/tools.py`、Research quality adapter | canonical engine、shadow parity、compatibility mapper、旧算法退出 |
| Workflow/contracts | `framework/specs/graph_semantics.py`（planned/new）、specs validation、workflow compiler/runtime、LLM/Agent budget、conversation/memory models | 无环 canonical graph 与 port-owned contracts；legacy freeze |

### 16.2 必须新增或扩展的测试区域

| Test area | 覆盖 |
| --- | --- |
| `tests/framework/harness` | named gate binding、worker score isolation、gate event/replay、budgeted failure handling |
| `tests/framework/tool` + approval stores | model identity、backend lifecycle、risk matrix、side-effect-before-approval invariant |
| `tests/interfaces/research` + `tests/infrastructure/research` | configured object graph、六个 entry/adapter surfaces factory parity、各自 transport/adapter contract、recorded outer workflow/inner RAG session identity、actor/tenant、restart/concurrency、adapter allowlist、shared Source provider |
| Source business/infra/interface tests | golden URL、taxonomy/retry、shared quota、live SourceError mapper、历史 persisted SourceError codec/real-reader round-trip、17-field public `RawSourceItem` cross-entry parity、entry/Research/Harness composition gates |
| Analysis quality tests | shared golden corpus、shadow diff classification、engine identity、persisted payload decode |
| Workflow/storage contracts | fallback graph parity、budget parity、conversation/vector backend conformance |

### 16.3 不应顺手修改

- 阶段 18 已完成的 artifact integrity/path/checksum 设计，除非新增 contract test 证明本阶段造成回归。
- 阶段 19 的 canonical event、outbox/inbox、sequence、replay、SQLite/PostgreSQL event store 和 OTel/W3C 设计。
- Parser/RAG backend 算法、frontend/UI、multi-host scheduler、distributed Source limiter 或新增 source provider。
- 与当前 change 无关的 public API、OpenAPI schema、数据库迁移和生成文件。

---

## 17. 审查发现与 Requirements -> Tasks -> Tests 追踪

### 17.1 Finding -> requirement 决策闭环

| Finding | 类型/分类 | 为什么不是有意策略差异 | Requirement / canonical owner | Change / test oracle | 状态 |
| --- | --- | --- | --- | --- | --- |
| H1 Worker score 形成 verdict/route | 架构边界 | 同一 worker 输出跨越 candidate 与 deterministic decision，两条路径没有独立领域输入 | HAR-001、004；`framework/harness` | archived gate change；worker score matrix 中 route 不变 | 已收敛基线，保留回归 |
| H2 named gate 未解析仍成功 | 架构边界 | workflow 已声明 gate，跳过执行不是“无 gate”变体 | HAR-002、003、006、007；gate registry | archived gate change；unknown gate 时 `worker_calls=0` | 已收敛基线，保留回归 |
| R1 默认 Research 进入 unconfigured/in-memory path | 功能重复/竞争路径 | 默认入口与显式 runtime 接收相同请求，却只有前者永久 503 且不可持久化 | RES-001、002、008、011；已落地的 `interfaces/composition/research.py` composition root | Research change；configured object graph + restart read + six-surface recorded parity | `12ed843a` 已交付，staged-only candidate 与 final commit tree 一致；保留 regression，U7 live provider readiness 仍单独未确认 |
| T1 Tool/Worker approval DTO 竞争 | 重复代码 | 字段、状态和持久化用途相同，差异来自复制后的 backend 漂移 | TOOL-001..003；`framework/workers/approval` | Tool change；InMemory/LocalJson 及本切片新增 store 的 type/state contract | 已确认 |
| T2 四处 tool risk classifier | 功能重复 | 输入均为同一 ToolDefinition，调用入口不应改变 authorization | TOOL-004..007；framework Tool policy | Safety change 验证唯一注册，Tool change 验证全 inventory risk matrix | 已确认 |
| B1 Research/Harness adapter ownership 漂移 | 依赖拓扑 | application 组装 concrete controller 与 hexagonal port 不是领域变体；外层 workflow 与 bounded RAG session 是 parent/child contract，不是两个平行 controller | RES-003、004、009、010；Research ports + interface composition | Research change；recorded workflow/session identity、AST/import graph、MCP dependency acyclic | `12ed843a` 已收敛，保留边界与 replay regression |
| S1 Source URL/retry/taxonomy/mapper 多份规则 | 重复代码 | 同一 URL、exception、quota 和 SourceError 在不同入口产生不同结果；live object 与 persisted decode 是不同边界但都需要唯一 owner | SRC-001..006；第 6.2 节精确 owner | active Source change；golden/parity/object+persisted round-trip/shared ledger/四 gate evidence | Core 已由 `372027ac` 收敛并留有 evidence；当前状态与开放任务只引用第 1.1 节 |
| Q1 production/eval/Research 共享质量规则分叉 | 功能重复 | citation/support 输入输出一致；Research 特有 readiness 另有显式字段 | QLT-001..005；`business/layers/analysis/quality` | Quality change；golden diff 必须全部分类 | 已确认 |
| W1 validator/compiler/runtime graph 分叉 | 重复代码/依赖拓扑 | 三者消费同一 WorkflowSpec，fallback edge 不是可选策略；当前 compiler wrapper 反向依赖 specs，不能成为 specs 的下层 owner | WF-001；目标纯 `framework/specs/graph_semantics.py` | Workflow graph change；fallback/cycle/dataflow parity + import-cycle oracle | 已确认 |
| E1 experience ref 未持久化且 hash 伪造 | 架构边界 | ref/hash 对外承诺可查询 provenance，不是 presentation 变体 | RES-007；Harness skill experience store | Experience change；append/query/manifest hash | 已确认 |
| C1 budget/conversation/memory contract 疑似复制 | 疑似重复/依赖拓扑 | 当前只有目录/字段相似性，尚不能排除 budget scope、transaction、cursor/checkpoint 或 vector lifecycle 的有意差异 | WF-002..004；U10 先验证，owner 暂不迁移 | U10 A/B call graph、logical input/output、exception 与 persistence lifecycle matrix；确认后才创建 conditional child change | 未确认，不进入合并范围 |
| D1 legacy builder/facade 仓内静态不可达 | 死代码候选 | 仓内 `rg`/AST 无调用只是第一层证据，不能排除 public export、dynamic entry、包外 consumer 或历史 replay | WF-005..008；原 owner 冻结 | Inventory/freeze change + owner-local child changes；五类删除证据齐全才允许 delete | 部分确认，不可直接删除 |

### 17.2 Requirements -> tasks -> tests/evidence

下表是 requirement 到 accountable change 的 routing 基线，不替代各 change 内的逐 ID task ledger。切片进入 implementation 前必须在其 `tasks.md`/`evidence.md` 记录唯一 accountable task、测试/审计证据与 implementation commit；缺少该明细时，表中分组不能作为 requirement 完成证据。

| Requirements | Accountable change / task-ledger obligation | 必须测试/证据 | 关键 oracle |
| --- | --- | --- | --- |
| HAR-001..007 | `harness-deterministic-gate-enforcement`（accountable baseline；HAR-006 消费非 accountable 的 `durable-event-runtime` evidence） | worker forbidden fields、unknown gate、step/global gate selection、LLM score routing；`PLAN -> EXECUTE -> VERIFY` transition sequence；turn/replan/retry 的 `limit-1/limit/limit+1`；事件重复/缺失/乱序与 transcript replay；若现有 evidence 缺项则先创建 modified-requirement change 并转移 accountable mapping | verdict 只引用 deterministic gate result；未知 gate 或预算耗尽后 `worker_calls=0`；replay state/counter/scheduler decision 一致，invalid event stream fail-closed |
| HAR-008..009 | `harness-side-effect-authority-closure` | forged worker authorization/memory/publication/skill-promotion fields、gate/approval/budget terminal states、active skill/release store 与 canonical/published/quarantine namespace read/write isolation、atomic publication | unauthorized side effect/memory/published index/active-skill writes 为 `0`；普通 run promotion count 为 `0`；terminal diagnostic 可由 quarantine reader 查询但不出现在 published/latest index |
| RES-001..006、RES-008..011 | `research-runtime-production-composition` completion | configured/unavailable object graph；HTTP Research route、HTTP MCP route、local MCP call、stdio loop、CLI direct commands、`NewsMCPServerAdapter` factory parity与各自 contract；recorded outer workflow/inner RAG session；Source shared binding；restart、concurrent runs、tenant visibility、AST dependencies | 无 fake/unconfigured/in-memory production dependency；workflow/session parent-child identity 可 replay；50-run isolation 串扰为 0；entry/adapter 不直达 executor/store |
| RES-007 | `research-experience-memory-provenance` | experience append/query、real package hash、gate failure/no-promotion | ref 可查询；普通 run promotion count 为 0 |
| TOOL-001..003、TOOL-005..007 | `tool-governance-canonicalization` | type identity、InMemory/LocalJson 及新增 store 的 pending/decision/duplicate/expiry/secret-rejection contract、risk signal conflict golden matrix、Harness approval、消费 canonical registry 的 object-graph/AST contract | 所有 store 的 status/error/immutability 一致，secret rejection 后 record count 为 `0`；所有入口得到同一 risk/approval/reason decision；side effect 在 durable approval 前为 `0`；不创建第二 registry |
| TOOL-004 | `framework-runtime-safety-hardening` | unique built-in registration、registry partition、duplicate fail-closed、custom-provider forwarding | 每个 built-in name 只有一个 registration owner |
| SRC-001..006 | `source-policy-contract-convergence` | URL golden corpus、retry/status matrix、cross-entry limiter、taxonomy、live object mapper、persisted codec/real reader、17-field public item parity、connector factory、entry/Research/Harness composition evidence | 相同 input 得到相同 identity/retry/quota/error/public payload；core、entry、Research、Harness gate 分别可定位，最终共用一个 ledger 或有 explicit unsupported Harness decision |
| QLT-001..005 | `analysis-quality-contract-convergence` | old/new parity snapshot、production/eval identity、Research adapter、artifact/persistence projection、100-run determinism | `unclassified_diff_count=0`；一个生产算法 owner |
| WF-001 | `workflow-canonical-graph-semantics` | fallback-only、cycle/dataflow、read_keys、compiler/runtime route parity、AST import-cycle | 三层 graph semantic disagreement 为 0；graph owner 到 specs/compiler/runtime 的依赖无环 |
| WF-002 | U10；仅证实重叠后创建 `framework-budget-contract-convergence` | router/Agent/Workflow production call graph、logical input、reserve/record/cost-rounding/exception/lifecycle matrix | 每个 case 明确 `merge|retain`；merge case 得到相同余额、拒绝和 cost，retain case 有明确 owner/理由 |
| WF-003 | U10；仅证实重叠后创建 `framework-conversation-contract-convergence` | message/compaction/cursor/checkpoint 与 LocalJson/Postgres transaction/recovery round-trip matrix | 每个 case 明确 `merge|retain`；不得仅凭 structural typing 宣称重复 |
| WF-004 | U10；仅证实重叠后创建 `framework-memory-document-contract-convergence` | memory record/document 与 Local/Vector/Qdrant identity/query/lifecycle matrix | 每个 case 明确 `merge|retain`；backend DTO 不因字段相似自动成为 framework contract |
| WF-005..006 | `framework-legacy-inventory-and-freeze` | AST/import/export、dynamic entry、replay fixture、package consumer inventory | 新增 legacy caller 为 0；未确认 public consumer 的 symbol 不删除 |
| WF-007 | `framework-fixture-domain-boundary` | fixture import graph、production package exclusion、Research regression parity | framework fake 无 Research-specific DTO/rule；测试行为不变 |
| WF-008 | owner-local `*-legacy-retirement` child changes | 每个 candidate 的 production/dynamic/public-export/persistence/replay 五类证据与替代测试 | 无跨 owning-area delete commit；undocumented compatibility 为 0 |
| Architecture | 各 change architecture batch | AST/import rules、composition owner、framework domain neutrality、legacy freeze | 禁止规则精确，无 blanket ignore |
| Required backend qualification | 被修改或被声明支持的 persistence backend | real-service Redis/Postgres/Qdrant conformance | 对应 contract suite 必须通过，否则撤回支持声明且阶段不得标 `FINAL` |
| Optional external-provider E2E | release qualification | credential-gated arXiv/LLM | ordinary smoke 不依赖外部 provider；live failure 与 deterministic contract failure 分开报告 |

Runtime/contract requirement 必须有可执行 regression 或 contract test；migration/parity requirement 必须有 committed golden corpus、差异 decision record 与兼容快照；retirement/compatibility requirement 必须有 import/export、dynamic entry、persisted replay、package consumer 与替代测试证据。流程依赖只作为明确的 change gate，不得用源码字符串或文件存在性测试充数。Boundary tests 应使用 AST/import graph；composition tests 应检查真实对象图和行为；backend tests 应复用参数化 contract suite，同时保留各 backend 的事务/SQL/锁断言。

---

## 18. 验证命令

每个 change 运行自身 focused suite；阶段级 release gate 至少包含：

```powershell
openspec validate --all --strict
python -m scripts.dev compile
python -m scripts.dev smoke
git diff --check
```

如果 change 修改 PostgreSQL、Redis、Qdrant 或 live transport adapter，必须额外运行其 backend contract suite，并记录依赖缺失、credential skip 和真实代码失败的区别。任何被本阶段修改或在阶段 `FINAL` 中声明支持的 Redis/PostgreSQL/Qdrant backend，都必须在真实服务上通过对应 contract suite；缺失服务会阻断该 backend 的支持声明和阶段 `FINAL`，不能用 fake 通过替代。只有 arXiv/LLM 等外部 provider 的 live E2E 可以作为不阻断 ordinary gate 的 optional qualification。不得用新增 `skip/xfail` 关闭本 PRD 的 regression。

---

## 19. 可观测性与运行指标

| Metric/Event | 用途 | 敏感信息规则 |
| --- | --- | --- |
| `harness_gate_resolution_failed_total` | 发现未知/缺失 gate | 只记录 gate id/version、workflow/step id |
| `harness_worker_verdict_field_rejected_total` | 发现 worker 越权输出 | 不记录 raw LLM output |
| `research_composition_mode` | configured/unavailable 与 capability readiness | 不记录 env value、credential、filesystem absolute path |
| `tool_risk_policy_disagreement_total` | migration shadow 阶段比较旧/新 classifier | 只记录 tool name/version 和 decision code |
| `source_rate_limit_decision_total` | 验证跨入口共享 quota | 记录 canonical domain hash，不记录完整敏感 URL/query |
| `quality_engine_version` | 追踪 canonical engine 与 compatibility adapter | 不记录 report body/evidence content |
| `legacy_runtime_invocation_total` | 证明 legacy path 是否仍有真实消费者 | 记录 symbol/path id，不记录 payload |

Migration shadow metric 只能用于验证 cutover，不得长期保留第二套 policy 执行。Compatibility window 结束时，disagreement/legacy metrics 应随旧实现一起删除或改为 invariant violation counter。

---

## 20. 发布、迁移与回滚

### 20.1 发布原则

- 先添加 contract tests、canonical implementation 和 adapters，再切生产 owner，最后删除旧代码。
- P1 修复默认 fail-closed；不得通过恢复 LLM verdict、in-memory production store 或重复 approval model 回滚。
- Public payload 和 persisted record 使用 dual-read/single-write 迁移；禁止永久 dual-write 两套事实模型。
- 每次切换保留明确 kill switch 只用于选择旧 adapter，不允许关闭 quality/authorization gate。

### 20.2 回滚、隔离与前向修复

| Surface | 处置类型 | 触发门槛 | 决策 owner | 目标/动作 | 数据与回滚后 oracle |
| --- | --- | --- | --- | --- | --- |
| Harness gate registry | Rollback | 任一 pre-cutover 合法 workflow corpus 被误拒，或 recorded replay verdict 不一致 | Harness runtime owner | 切回上一已资格化 registry mapping/version；不得恢复 worker score verdict | 不改写历史 gate event；compatibility corpus、replay 和 unknown-gate fail-closed 全部通过 |
| Research production factory | Containment + rollback | 任一已资格化 configured graph 无法启动、recorded analysis 失败或 restart read 失败 | Research runtime owner | 先进入 typed unavailable containment，再切回上一已资格化 factory/adapter；不得选择 fake/in-memory success path | 已写 run/artifact 保持 dual-read；object-graph、recorded analysis、restart-read contract 通过 |
| Tool risk/approval | Forward-fix，必要时 policy rollback | Golden matrix 出现任一未分类差异、合法 read-only tool 被误阻断，或 approval 前发生 side effect | Tool governance owner | 修正或切回上一 policy version；高风险仍 fail-closed，不允许 bypass approval | 不重写既有 approval decision；risk matrix、duplicate decision 和 pre-approval side-effect oracle 通过 |
| Source policy/composition | Rollback | Shared-ledger invariant violation 大于 0、实际 attempts 超出 retry matrix，或 golden case 出现误限流/请求放大 | Source runtime owner | 切回上一已资格化 composition binding，同时保留单一 shared limiter；不得复制 ledger | 历史 identity/ref 继续 dual-read；quota、retry、taxonomy 和 persistence compatibility matrix 通过 |
| Analysis quality engine | Rollback cutover/adapter | `unclassified_diff_count > 0`、公共 payload snapshot 改变，或 persisted projection 无法读取 | Analysis Quality domain owner | 切回上一 engine/compatibility adapter version；不得降低 deterministic gate 或删除 parity evidence | 不改写历史 artifact；golden parity、payload/persistence round-trip 和 gate regression 通过 |
| Workflow graph semantics | Containment + rollback | Compatibility corpus 出现 compile/runtime route 分歧，或历史 checkpoint replay 失败 | Workflow runtime owner | 停止新 graph cutover并切回上一 graph adapter/version；保留历史 reader/upcaster | 不改写 checkpoint/event；fallback/cycle/dataflow/route parity 与 replay 通过 |

每个 production cutover 的 OpenSpec `design.md`/`evidence.md` 必须在切换前填入 `trigger_metric`、观测窗口与阈值、`decision_owner`/on-call、精确 `rollback_target`（version/commit/flag）、数据兼容处理、`post_rollback_oracle` 和 `max_recovery_time`。仓库当前没有提供 named on-call、生产观察窗口、qualified rollback target 或 RTO；这些值属于第 22 节 U9 的 release/operator 输入，不能由实现者推测。上表的零容忍 invariant 不得被切片放宽；字段未填或未完成一次 recorded/fault-injection rehearsal 时，不得执行 production cutover，但不阻断独立代码切片完成 offline verification。

---

## 21. 风险与对策

| 风险 | 对策 |
| --- | --- |
| PRD 范围过大形成 mega change | 强制按第 14/15 节拆分 OpenSpec 与 commit；P1、Research、Source、Quality、Workflow 独立验收 |
| 将有意 backend/domain 变体误删 | 删除前执行 ownership、I/O lifecycle、external import、persisted contract 四项复核 |
| Quality 新实现更严格导致大量 report 被拒 | 先运行 shadow parity/golden review，再切 production；不通过降低 gate 阈值掩盖差异 |
| Architecture allowlist 变成逃生口 | 只允许精确 module/type，禁止目录级/前缀级 blanket exception |
| Active/unarchived OpenSpec 并行修改相同文件 | 每个 change 声明 file owner；Source、Research、framework safety、durable event 等 active/unarchived owners 先做 overlap check |
| 删除 public legacy export 破坏包外消费者 | 一个 release deprecation、usage telemetry/import audit、migration note 后再删 |
| Live Redis/Postgres/Qdrant 与 fake 行为不同 | contract suite + real-service CI；被修改或被声明支持时必须通过，外部 provider E2E 才可 optional |
| 修复 Source/Tool policy 时引入新的共享 god module | contract 放 owning domain；adapter 保持薄；禁止无 owner generic utils |
| Active change 的 task ledger 早于阶段 20 requirement IDs | 当前数字只引用第 1.1 节；Research `evidence.md` 已回填逐项 `RES-* -> task -> test/evidence -> implementation commit/status`，implementation 为 `12ed843a`。其他 change 仍须在各自交付前建立相同映射，且不得把单一 change 的 task completion 解释为阶段 20 requirement 全部完成 |

---

## 22. 未确认项与决策门

下列项目缺少足够运行、外部 consumer 或真实 backend 证据，当前不得写成“可合并”或“可安全删除”。每项必须由下表 owner 在指定 evidence 中记录验证或明确保留决策；验证仍不充分时按默认处置保留现状，不得让不确定性扩散为新的 compatibility path。

| ID | 未确认项 | Accountable owner / evidence | 决策期限与阻断项 | 验证方式与默认处置 |
| --- | --- | --- | --- | --- |
| U1 | Legacy public exports 是否有包外消费者 | `framework-legacy-inventory-and-freeze` owner；其 `evidence.md` compatibility registry | 每个 public export 删除提案前；阻断该 symbol 删除与相关 owner-local retirement final | package/export inventory、文档/entry-point、release telemetry 或 consumer confirmation；未证实时保留并设置 owner/expiry |
| U2 | Production Harness 是否应提供 Source ToolRegistry/ToolPort capability，以及唯一 composition owner 在哪里 | Tool governance/Harness composition owner + Source integration owner；在 Source `evidence.md` 与条件 child change 交叉引用同一 evidence id | P2A-Harness 前；阻断 Source task 3.7 和 Source change overall completion，不阻断独立 Research gate | runtime composition probe、registry inspection、recorded Harness run；确认支持则接同一 provider，确认不支持则发布 explicit capability decision；不得造第二 registry/fake path |
| U3 | Redis/PostgreSQL/Qdrant 与 local/fake contract parity | 每个 backend adapter owner；记录在触碰或声明支持该 backend 的 change `evidence.md` | 对外支持声明与 phase `FINAL` 前；阻断对应 backend 支持声明 | service-gated contract CI + backend-specific SQL/lease/transaction assertions；未通过时撤回支持声明 |
| U4 | 测试 fixture/mock/setup 是否为真实重复 | 对应测试 owning area maintainer；`framework-fixture-domain-boundary` 或 owner-local change evidence | 抽取 shared fixture 前；只阻断该次抽取，不阻断保留现状 | AST/fixture use graph、参数矩阵、mutation/failure-path comparison；生命周期不一致时保留独立 fixture |
| U5 | pagination/config/serialization helper 是否重复 | 当前模块 owner；仅在拟议 helper change 的 `evidence.md` 建账 | 新 generic helper 或合并提交前；只阻断该重构 | 静态调用图 + golden cases + exception/compatibility matrix；证据不足不新增 helper、不强制合并 |
| U6 | 旧 analyzer/report DTO/WorkflowExecutor/storage adapter 是否可删除 | `framework-legacy-inventory-and-freeze` owner + 对应 owner-local retirement owner | 每个 candidate 删除前；阻断该 candidate 删除 | `rg`/AST/export/entry-point、fixture replay、package consumer audit；五类证据不齐则冻结并保留 |
| U7 | Live arXiv/LLM Research 默认 composition 可用性 | Research release owner；`research-runtime-production-composition/evidence.md` live qualification | 宣称 live provider ready 前；不阻断 ordinary offline gate | 独立 credential-gated smoke，记录 provider/model/capability code且不记录 secret；缺证据时不得作 live readiness 声明 |
| U8 | 外部 HTTP/MCP/SDK 对 payload 的隐式依赖 | Interface contract owner；记录在实施 payload cutover 的 change `evidence.md` | 删除/重命名字段前；阻断对应 breaking change | OpenAPI/JSON snapshot、SDK fixture、release note 与 consumer feedback；未确认时保留 additive/dual-read 兼容窗 |
| U9 | Production cutover 的 named on-call、观察窗口、qualified rollback target 与 `max_recovery_time` | Release/operator owner；记录到每个 cutover change 的 `design.md`/`evidence.md` 与演练记录 | production cutover 与阶段 `FINAL` 前；不阻断独立代码切片、offline contract 和 smoke 完成 | 由实际运营 owner 指定角色、版本/commit/flag、窗口、阈值与 RTO，并完成一次 recorded/fault-injection rehearsal；信息缺失时保持 cutover disabled，不编造 owner 或目标 |
| U10 | Budget、conversation、memory DTO/contract 是否是真正重复 | 对应 framework/runtime/storage owner；先在共享 evidence ledger 建立 A/B matrix，再决定是否创建 WF-002..004 child change | 任何 canonical owner 迁移、generic mapper 或 DTO 删除前；只阻断该类收敛，不阻断保留现状 | 生产调用图、相同 logical input/output、异常/validation、transaction/cursor/checkpoint、backend lifecycle 与 persisted round-trip；每个 case 标记 `merge|retain` 和置信度，证据不足默认保留 |

---

## 23. Definition of Done

### 23.1 P1 authority

- [ ] Worker output 不能直接形成 Harness quality verdict 或 route。
- [ ] 所有 step quality gates 可解析、可执行、可 replay；未知 gate fail-closed。
- [ ] `PLAN -> EXECUTE -> VERIFY` 每次 phase transition 与 retry/replan/terminal decision 均持久化；`max_turns`、`max_replans` 和 retry budget 边界测试通过，耗尽后无额外 worker/gate 调用；重复事件幂等，缺失或乱序 replay fail-closed。
- [ ] Worker 不能直接授权 tool、memory write、skill promotion 或 publication；未通过 gate/approval 的 candidate 只允许进入隔离 quarantine namespace，不进入 canonical/published store 或 published/latest index。
- [ ] 默认 configured Research HTTP/MCP/CLI 进入真实 runtime 和 durable store。
- [ ] Tool approval 使用唯一 canonical worker model，重复 decision 在所有 store 中一致拒绝。

### 23.2 Contract convergence

- [ ] Tool risk classification 在 discovery/schema/executor/inspection/Harness 中一致。
- [ ] Source URL、limiter、retry、taxonomy 和 mapper 各只有一个决策 owner。
- [ ] Source core、entry binding、Research binding 与 Harness Source-tool capability 分门禁验收：默认 Research arXiv package/PDF 复用同一 Source provider/ledger；Harness 绑定唯一 production ToolRegistry/ToolPort，或有经批准的 explicit unsupported decision；不存在为完成 task 新建的第二 registry、runtime 或 limiter。
- [ ] Production/eval 通用 quality 规则使用同一 engine。
- [ ] Workflow validation/compiler/runtime 使用同一 pure graph semantics owner，且依赖图不存在 `specs -> compiler -> specs` 环。
- [ ] U10 对 LLM budget、conversation 和 memory document 给出逐 case `merge|retain` 结论；已证实重复的路径不再依赖 structural typing，确认是领域/backend 变体的路径保留独立 owner 与 contract test。

### 23.3 Boundaries and compatibility

- [ ] `business/research` 不依赖 legacy、interfaces 或 infrastructure；普通 application/service 不分散构造 Harness controller，指定 runtime boundary 只依赖获批的 domain-neutral contract。
- [ ] Production analysis recorded run 引用 canonical outer workflow id/version/checksum 和 phase/gate events；bounded RAG session 只作为可追踪子会话或显式 standalone ask scope，不形成第二条外层控制路径。
- [ ] `infrastructure/research` 只依赖精确获批的 Research domain/port contract，architecture smoke 通过。
- [ ] RES-009 所列 Research 六入口及本阶段新增或修改的 interface transport 只调用 application-layer service 或明确获批的 application use case；MCP inbound server 与 outbound ToolRuntime adapter 依赖无环、状态隔离。其他历史 interface surface 只有建立独立 finding、requirement 与 OpenSpec owner 后才纳入迁移。
- [ ] HTTP/MCP/SDK、approval JSON、quality artifacts、`SourceError`、17-field public `RawSourceItem`、event/checkpoint 和 storage payload compatibility 有 committed tests。
- [ ] 每个 compatibility adapter 有 owner、删除条件和期限。

### 23.4 Delivery evidence

- [ ] HAR-001..009、RES-001..011、TOOL-001..007、SRC-001..006、QLT-001..005、WF-001..008 共 46/46 个 requirement IDs 均映射到单一 accountable OpenSpec change，并在该 change 内映射到单一 accountable task、test/evidence 和 implementation commit；task 可以覆盖多个同边界 requirement，但一个 requirement 不得有多个完成 owner。每项还必须具备与 requirement kind 匹配的 passing regression/contract test 或 migration/retirement 审计 evidence；未完成项不得以 waiver 标记阶段 `FINAL / IMPLEMENTED`，需求撤销必须先修改 PRD 与对应 OpenSpec。
- [ ] 所有建议 change 通过 `openspec validate <change> --strict`。
- [ ] `openspec validate --all --strict`、`python -m scripts.dev compile`、mandatory `python -m scripts.dev smoke` 和 `git diff --check` 全部通过。
- [ ] 被修改或被声明支持的 Redis/Postgres/Qdrant backend 在真实服务上通过 contract suite；optional arXiv/LLM live E2E 结果与 ordinary offline gate 分开记录。
- [ ] 删除清单附 `rg`/import graph、包外 consumer、dynamic entry、persisted replay 和替代测试证据。
- [ ] PRD、OpenSpec tasks、tests 和 implementation commits 建立 requirements traceability。
- [ ] 第 22 节每个未确认项都有验证记录或带 owner/expiry 的明确保留决策。
- [ ] Compatibility registry 字段完整且 `overdue=0`；所有 migration kill switch 都有 retirement evidence。
- [ ] 第 22 节 U9 已由实际 release/operator owner 解决；每个 production cutover 已填写第 20.2 节 rollback contract，并保存一次 recorded 或 fault-injection rehearsal、恢复时长和 post-rollback oracle 结果。

阶段 20 只有在上述条件全部满足时才能标记 `FINAL / IMPLEMENTED`。局部 change 完成不得用于宣称整个阶段已收敛。

---

## 24. 可复制给 Codex 的实施提示

实施任一阶段 20 change 时，Codex 必须：

1. 只读取本 PRD 中该 change 对应的 requirement、owner、兼容矩阵和测试 oracle，不把 umbrella scope 一次性实现。
2. 先在本地执行 live repro 与 failing regression，把命令、失败 oracle 和结果记录到对应 OpenSpec `evidence.md`；不得把 red commit 合入可合并历史。
3. 读取 active OpenSpec/file ownership，避免与 Research、framework safety、durable event 并行 change 修改同一 contract。
4. 使用 canonical owner 和显式 adapter，不新增第二套 policy、DTO、graph、store 或 compatibility path。
5. Regression 与根因修复形成 green implementation commit；完成 focused tests、architecture tests、strict OpenSpec、compile、mandatory smoke 和 diff check 后才允许合并最终切片。
6. 删除 legacy 前附 production/dynamic/public-export/persistence/replay 证据；证据不完整时保留并登记 expiry，不猜测安全删除。
