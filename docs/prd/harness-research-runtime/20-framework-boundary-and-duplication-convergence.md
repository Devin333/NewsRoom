# 阶段 20：框架边界与重复实现收敛 PRD

> Document status: READY_FOR_OPENSPEC
>
> Implementation status: NOT_STARTED
>
> Version: v1.0
>
> Priority: P1（控制权与生产运行阻断）/ P2（架构与契约收敛）
>
> Scope: Harness VERIFY authority、Research production composition、Tool approval/policy、Source governance、Analysis quality、Workflow/framework contract 与 legacy cleanup
>
> Source audit: 2026-07-18 当前工作树“框架层与重复实现专项审查”
>
> Existing OpenSpec owners: `research-runtime-production-composition`、`framework-runtime-safety-hardening`、`durable-event-runtime`
>
> Depends on: 阶段 1/2 Harness authority、阶段 8/9 legacy deletion rules、阶段 19 durable gate-event contract，以及上述 active changes 的明确 file ownership
>
> Last updated: 2026-07-18

> 状态说明：`READY_FOR_OPENSPEC` 表示问题、目标、非目标、ownership、兼容边界、实施顺序和验收标准已经形成 PRD 基线，但本 PRD 不授权把全部工作塞进一个 change。每个实施批次必须先建立或更新对应 OpenSpec delta，并通过 strict validation。文档被后续 PRD 取代时标记 `SUPERSEDED`。

## 0. 一句话结论

NewsRoom 当前最需要的不是增加新的 framework abstraction，而是让已经存在的运行能力回到唯一权威路径：**Harness 的 deterministic gate 必须是 quality/routing 的唯一事实源，Research 默认入口必须进入真实 runtime，approval/tool/source/quality/workflow 等共享契约必须各有一个 canonical owner。**

本阶段以小步、可回滚的 contract convergence 取代大规模重写。它保留现有公共 API、持久化格式、event replay、合法 backend 变体和已验证的 Harness 有界状态机，只收敛已经通过调用关系、运行探针或测试门禁证明存在的冲突实现。

---

## 1. 背景与审查依据

### 1.1 当前运行基线

截至 2026-07-18，当前工作树的验证结果为：

| 检查 | 结果 | 说明 |
| --- | --- | --- |
| `python -m scripts.dev smoke` | `1014 passed, 23 skipped, 1 failed` | 唯一失败为 infrastructure boundary test，报告 7 个 `infrastructure/research -> business` imports |
| Source focused suite | `67 passed` | 现有 happy path 通过，但未覆盖跨入口 policy parity |
| Analysis quality focused suite | `38 passed` | 两套 quality 实现各自通过，未覆盖生产/评估 parity |
| Research/RAG route suite | `20 passed` | 主要依赖注入 fake 或显式 service，未证明默认 production composition |
| Workflow contract suite | `31 passed` | 未覆盖 fallback-only graph 的 compiler/runtime parity |
| `openspec validate --all --strict` | 510 项通过 | 说明规格语法有效，不代表 live implementation 已满足全部约束 |
| `git diff --check` | 通过 | 当前审查没有格式错误证据 |

现有 Harness 在 `PLAN -> EXECUTE -> VERIFY`、`max_turns`、`max_replans`、retry budget 和 durable transition 方面有明确实现与测试。本阶段不替换这套状态机，只修复 VERIFY authority 和外围 composition/contract 漂移。

### 1.2 已确认问题

| ID | 级别 | 已确认问题 | 关键证据 | 实际后果 |
| --- | --- | --- | --- | --- |
| H1 | P1 | Worker 自报 `quality_score` 会被转成 `HarnessQualityVerdict` 并参与 `ON_VERDICT` 路由 | `framework/harness/workers/result.py:18-35`；`control_plane/harness.py:1572-1589`；`routing.py:70-87` | LLM/subagent 可间接决定 quality 和下一步 |
| H2 | P1 | `HarnessStepSpec.quality_gate` 只被序列化，没有 fail-closed registry 绑定 | `framework/harness/workflow/step.py:68-98`；`control_plane/harness.py:1033-1040` | workflow 声明的 gate 可能从未执行或进入 replay |
| R1 | P1 | 默认 HTTP/MCP 构造裸 `ResearchApplicationService`，固定使用 unconfigured use case 和进程内 store | `interfaces/api/app.py:102-123`；`interfaces/services/research_service.py:100-110,315-323,485` | 真实 `source -> evidence -> analysis -> quality -> artifacts` 链路在默认入口不可达 |
| T1 | P1 | `ToolApprovalRequest.to_worker_approval_request()` 返回 tool 模块中的重复 DTO | `framework/tool/governance/approval.py:64-150`；`framework/workers/approval/model.py:74-167` | approval 幂等、secret validation、status 和序列化依赖 store backend |
| T2 | P2 | Framework、infrastructure、business 和 `ToolPolicy` 各自维护危险工具分类 | `framework/tool/registry/catalog.py:192-201`；`infrastructure/tools/catalog.py:146-155`；`business/tools.py:204-230`；`framework/tool/models/policy.py:154-168` | 同一个 ToolDefinition 在 discovery/schema/executor 中可能得到不同授权结论 |
| B1 | P2 | Research/Harness adapter ownership 与 architecture test 不一致 | `business/research/services/rag_policy.py:3-70`；`business/research/application/paper_rag_session.py:5-115`；`tests/architecture/test_infrastructure_boundary.py:24-34` | business application 直接构造 Harness DTO/controller，同时合法 outbound adapter 无法通过 smoke |
| S1 | P2 | URL、rate limiter、retry、error taxonomy 和 mapper 存在重复及行为漂移 | `business/layers/signal/source_processing/url_normalization.py:10-43`；`source_tool_runtime.py:43-87,171-202`；`infrastructure/external/sources/fetch_policy.py:88-172` | quota 分裂、retry 结论不一致、canonical id 漂移和 lineage 字段丢失 |
| Q1 | P2 | 生产 `quality_records.py`、评估 `analysis/quality/*` 和 Research gate 三条质量路径并存 | `business/layers/analysis/tools.py:8-17,88-139`；`business/layers/analysis/quality/eval_dataset.py:69-95` | 同一 report/evidence 在不同入口可能得到不同 pass/score |
| W1 | P2 | Spec validator、compiler 和 runtime 对 fallback edge 的 graph 语义不一致 | `framework/specs/validation.py:171-190`；`framework/workflow/compiler/compiler.py:221-251`；`execution_loop.py:626-679` | 合法 recovery workflow 可能通过 spec validation 却无法 strict compile |
| E1 | P2 | Research 返回未持久化的 `skill_experience_refs`，并写入固定伪 package hash | `business/research/application/single_paper_runtime.py:586-650` | experience 无法查询/replay，skill provenance 不可信 |
| C1 | P2 | Budget、conversation 和 memory document contract 在 framework/storage 侧重复 | `framework/llm/budget`；`framework/agent/runtime/llm.py`；`framework/agent/messages/message.py`；`infrastructure/storage/conversation/models.py` | 同一跨层对象依赖 structural typing，validation 和异常语义逐步漂移 |
| D1 | P3 | 私有 legacy builder、薄 facade 和测试脚手架已确认仓内不可达或重复 | `business/layers/analysis/pipeline.py:122-363`；`business/layers/relation/relation_validator.py:6-8` | 维护者可能修改无效路径，测试 setup 成本持续增加 |

### 1.3 已执行反例探针

以下探针均在当前工作树上只读执行，未修改仓库：

| Probe | 当前结果 | 目标结果 |
| --- | --- | --- |
| LLM step 声明不存在的 `quality_gate="DefinitelyMissingGate"` | run 仍为 `succeeded` | compile 或 run start 前 fail-closed |
| LLM worker 返回 `quality_score=0.95` | 形成 verdict 并按 `ON_VERDICT` 路由 | 只能作为 candidate observation，不能直接形成 verdict |
| Tool approval 转换类型检查 | 返回类型不属于 worker `ApprovalRequest` | 返回 canonical worker model |
| InMemory approval 重复 decision | 第二次 decision 仍成功 | 抛出稳定 `ApprovalAlreadyDecidedError` |
| read-only ToolDefinition 危险分类矩阵 | `mcp.foo`、`source.fetch_url`、`local_json.save`、`qdrant.upsert` 结论不一致 | 所有入口使用同一 policy decision |
| fallback-only workflow | spec validation 通过，strict compiler 报 `unreachable_step` | validator/compiler/runtime 使用同一 graph |

实施任何修复前，必须先把这些探针转成 committed regression tests。聊天记录和本 PRD 中的输出不能替代可重复测试。

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
| Configured 默认 Research 成功路径 | HTTP、HTTP MCP、local MCP、stdio/CLI 均通过同一 factory；不包含 unconfigured use case 或 in-memory production store |
| Approval canonical model | ToolExecutor、InMemory、LocalJson 及 interface service 类型/状态语义 100% 一致 |
| Tool risk parity | 同一 ToolDefinition 在 catalog、schema export、executor、inspection 中决策 100% 一致 |
| Source policy parity | URL golden、retry matrix、taxonomy、shared quota 和 `SourceError` round-trip 100% 通过 |
| Production quality owner | 每个共享 citation/support/score/editor 规则只有一个生产实现 |
| Workflow graph parity | fallback-only、failure edge、cycle、dataflow 和 runtime route 使用同一 adjacency contract |
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
| `interfaces/api|cli|mcp` | transport parsing、actor/request context、调用 application service | 构造 process-global business runtime、直接访问 executor/store |
| `interfaces/composition` | 选择 concrete adapters、settings、lifecycle/cache | 表达 Research 业务规则或复制 authorization policy |
| `business/research` | domain model、use case、candidate worker contract、deterministic Research rules、声明式 workflow metadata；指定 runtime boundary 可消费 domain-neutral Harness contracts | import interfaces/infrastructure；在普通 application/service public contract 中暴露 Harness DTO；构造 concrete store/adapter |
| `infrastructure/research` | 实现 Research outbound ports、source/compiler/storage/RAG adapters | 依赖 Research application/services/workflows 或复制 domain rule |
| `framework/harness` | state、scheduler、gate registry、routing、transcript authority | Research/paper-specific DTO、fixture 或规则 |
| `framework/tool` | canonical tool model、risk/approval execution contract | business/infrastructure tool inventory ownership |

`infrastructure` 依赖 business-owned ports/domain DTO 是允许的 hexagonal adapter 方向，但必须由精确 architecture allowlist 表达。Blanket allowlist 不得扩展到 `business.research.application`、`services`、`workflows` 或 concrete parser/runtime implementation。

本阶段不全面禁止 `business/research -> framework`。Research 可以依赖经过批准的 domain-neutral Harness contract；需要收敛的是 `rag_policy.py`、`paper_rag_session.py` 等普通 service/application 模块分散构造 Harness DTO/controller，以及 framework 反向出现 Research-specific fixture/rule。`ResearchSinglePaperRuntime` 的最终位置与职责必须在 `research-runtime-production-composition` design 中明确，不能靠 import 移动暗中改变。

### 5.4 Compatibility first

- 现有 endpoint path、SDK method、approval JSON schema、quality artifact key、checkpoint/event schema 和 artifact ref 不得静默破坏。
- 迁移必须采用 expand -> dual-read/adapter -> cutover -> contract window -> delete。
- Compatibility adapter 必须有 owner、删除条件和最长一个 release window；不得成为第二条永久运行路径。

---

## 6. 目标架构与 canonical ownership

### 6.1 控制与运行路径

| 顺序 | Owner | 输入 | 输出 |
| --- | --- | --- | --- |
| 1 | Interface composition | settings、actor、transport request | application service + concrete port graph |
| 2 | Research application | Research request/domain refs | Harness run request + candidate worker ports |
| 3 | Harness PLAN/EXECUTE | workflow spec、state、budget | worker candidate result |
| 4 | Harness VERIFY | candidate result、deterministic gates | versioned gate results + verdict |
| 5 | Harness scheduler | verified verdict、explicit policy | replan/retry/route/halt/complete |
| 6 | Artifact/run/experience stores | accepted outputs、events、refs | durable records and queryable refs |

### 6.2 Ownership matrix

| Contract/能力 | Canonical owner | Adapter/consumer |
| --- | --- | --- |
| Harness gate registry/verdict | `framework/harness` | Research gates、Workflow declarations |
| Approval request/decision/status | `framework/workers/approval` | Tool wrapper、interfaces、LocalJson/Postgres stores |
| Tool risk decision | `framework/tool` policy/governance | framework/infrastructure/business registries |
| Research production graph | `interfaces/composition/research.py` | HTTP/MCP/CLI factories |
| Research domain/ports | `business/research` | infrastructure Research adapters |
| Source identity/canonical URL | business-owned Source contract | connectors、tools、health、mappers |
| HTTP retry/rate-limit execution | one infrastructure Source runtime policy | all connectors and interface compositions |
| Analysis quality engine | `business/layers/analysis/quality` | production tools、eval、Research adapter |
| Workflow graph semantics | one framework spec/compiler graph module | validation、compiler、dataflow、runtime |
| LLM budget | `framework/llm/budget` | Agent/Workflow adapters |
| Conversation/memory persistence DTO | owning port contract | LocalJson/Postgres/Qdrant mappers |
| Skill experience store/provenance | `framework/harness/skills/evolution` | Research memory/experience adapter |

---

## 7. 详细需求 A：Harness deterministic VERIFY authority

### 7.1 Requirements

| ID | Requirement |
| --- | --- |
| HAR-001 | `HarnessWorkerResult` 不得携带可直接解释为 route、quality verdict、approval、memory write 或 publication decision 的字段。保留模型自评分时必须命名为 observation，并且 gate/controller 不直接采用。 |
| HAR-002 | `HarnessStepSpec.quality_gate` 必须解析到 deterministic gate registry；未知、重复、版本不兼容或缺少依赖的 gate 在 run start 前 fail-closed。 |
| HAR-003 | 每个 step 只执行其声明 gate 加全局 mandatory gates；不得用一个不区分 step 的 gate 列表替代声明契约。 |
| HAR-004 | `HarnessQualityVerdict` 只能从 gate result aggregation 生成；默认 `passed=True` 仅允许明确声明“无 quality gate”的 framework utility step。 |
| HAR-005 | Gate failure 只能触发 spec/policy 允许的 retry、replan、repair、halt 或 fail，并继续受 `max_replans/max_turns/retry budget` 约束。 |
| HAR-006 | Transcript 必须记录 gate id/version、input refs/hash、结果、失败原因、聚合 verdict 和由此产生的 scheduler decision。 |
| HAR-007 | Research workflow 中声明的 gate 必须逐一映射；不存在的历史 gate name 必须删除或实现，不能仅作为 metadata 保留。 |

### 7.2 Acceptance

- 任何 `worker_type=llm|subagent` 的自报 score 都不能单独改变 route。
- `quality_gate="DefinitelyMissingGate"` 在执行 worker 前失败。
- Research paper-analysis workflow 的每个 gate name 都有 registry identity 和 committed execution test。
- Replay 使用已记录 gate result，不重新调用 LLM 或以当前默认值替换历史 verdict。

---

## 8. 详细需求 B：Research production composition 与边界

### 8.1 Requirements

| ID | Requirement |
| --- | --- |
| RES-001 | 复用 active `research-runtime-production-composition`，让 configured HTTP/MCP/CLI 默认入口共享 `ResearchApplicationService -> AnalyzePaperUseCase -> ResearchSinglePaperRuntime` production factory。 |
| RES-002 | Configured graph 不得包含 `_UnconfiguredAnalyzeUseCase`、Research fake、`FakeArtifactPort` 或 production `InMemoryResearchRunStore`；缺配置时返回 typed/sanitized unavailable service。 |
| RES-003 | 普通 `business/research/application` 与 `services` 的 public contract 只暴露 Research request/result/ports，不分散构造 `RAGSessionSpec`、`BoundedRAGSessionController` 或 concrete store；`business/research/workflows` 可保留声明式 Harness metadata，指定 runtime boundary 可消费 domain-neutral Harness control-plane contract。 |
| RES-004 | `infrastructure/research` 只依赖获批的 `business.research.domain|ports` contract；禁止依赖 application/services/workflows 和 concrete business runtime/parser implementation。 |
| RES-005 | `/ask` 与 `/rag-ask` 统一由注入的 Research application factory 管理；以显式 mode 保留 summary projection 与 chunk-RAG 差异，不保留 router-owned singleton。 |
| RES-006 | API actor 的 `tenant_id/user_id/memory_namespace` 必须进入 RAG retrieval、visibility、memory 和 transcript；tenant-aware 数据不允许在 tenant 缺失时静默全量放行。 |
| RES-007 | `SkillExperience` 必须先通过 Harness-controlled store 持久化，成功后才返回 ref；package hash 来自真实 released package manifest。普通 Research run 不得触发 promotion。 |
| RES-008 | Analysis、reader、ask、trace、artifact refs 和 experience refs 在 service/process 重建后仍可查询。 |

### 8.2 Architecture rule

`tests/architecture/test_infrastructure_boundary.py` 必须从“全部禁止”收敛为可解释规则：Research adapter 可以 import 稳定 port/domain DTO，但不得通过宽泛 `business.*` allowlist 掩盖 application/service/runtime 依赖。现有 7 个 violation 必须逐项迁移或收窄，不允许只添加目录级例外使 smoke 变绿。

### 8.3 Acceptance

- 默认 configured API 真实执行一次 recorded-transport Research analysis，并在新 service instance 中读取 analysis/trace。
- HTTP、MCP、CLI/stdio 使用同一 factory identity 和 durable store。
- `/rag-ask` 的 DI、actor/tenant propagation 和并发隔离有 route-level tests。
- 返回的每个 `skill_experience_ref` 都可查询；metadata 不出现 `fake` hash。
- `business/research` 继续不依赖 legacy `business/boards/paper_radar`、interfaces 或 infrastructure。

---

## 9. 详细需求 C：Tool approval 与 risk policy 收敛

### 9.1 Requirements

| ID | Requirement |
| --- | --- |
| TOOL-001 | 保留 tool-specific `ToolApprovalRequest`，删除重复 generic approval DTO；转换必须返回 `framework.workers.approval.ApprovalRequest`。 |
| TOOL-002 | InMemory、LocalJson 和后续 Postgres store 对 pending、decision、重复决定、expiry、secret rejection 使用同一语义。 |
| TOOL-003 | 定义一个以 `ToolDefinition` 为输入的 canonical risk decision；name list 只能作为 legacy/default fallback，side effect、approval metadata 和 explicit dangerous flag 优先。 |
| TOOL-004 | Framework registry 只拥有 base tools；infrastructure/business 追加各自 definitions，但不得重写 filter/classifier。 |
| TOOL-005 | Catalog、schema export、batch executor、ToolExecutor、inspection 和 Harness tool gate 必须调用同一 risk decision。 |
| TOOL-006 | `business/tools.py` 不再选择 concrete infrastructure connectors；concrete binding 移到 interface composition。 |
| TOOL-007 | 本阶段复用 `framework-runtime-safety-hardening` 的 unique registration 工作，但不得把 approval/risk semantic 修复偷偷并入未声明 task。 |

### 9.2 Acceptance

- `to_worker_approval_request()` 的类型 identity、serialization 和 decision lifecycle 在所有 store contract tests 中一致。
- 重复 decision 稳定失败，失败不覆盖原 reviewer、time 或 modifications。
- 同一工具全集在所有入口的 risk classification 完全一致。
- `mcp.*`、`source.fetch_url`、`local_json.save`、`qdrant.upsert`、`artifact.write`、`postgres.query` 有明确 golden decisions。
- `ToolExecutor` 在 approval record durable 前不执行 side effect。

---

## 10. 详细需求 D：Source runtime policy 收敛

### 10.1 Requirements

| ID | Requirement |
| --- | --- |
| SRC-001 | 选择一个 canonical URL identity contract，锁定 scheme/host/port/path/trailing slash/query key/tracking key/relative URL 行为；删除逐行重复实现。 |
| SRC-002 | Default connector、source tool、health probe 和 runtime assembly 对同一 domain 使用共享 limiter instance；不能按 connector class 或入口拆配额。 |
| SRC-003 | Retry decision 由一个 policy 实现，明确 HTTP status、timeout、URL/config error、unknown error 和 exhausted budget 语义。 |
| SRC-004 | Error taxonomy 只有一个规则实现；connector-specific keyword 只能作为显式扩展输入，不复制整套 classifier。 |
| SRC-005 | Business/infrastructure DTO 可以不同，但必须通过一个显式 mapper；所有 SourceError 字段包括 `request_ref`、`response_ref`、`occurred_at` 完整 round-trip。 |
| SRC-006 | 八个 connector 的重复 `_source_error()` 收敛为共享 construction helper，同时保留 connector-specific classification。 |

### 10.2 Acceptance

- URL golden corpus 在 connector、SourceRef、signal pipeline 和 tool path 输出一致。
- 同域跨 RSS/HTML/tool/health 的第 N+1 次请求在 network fetch 前被统一 rate-limit。
- Retry matrix 对 HTTP 4xx/5xx、timeout、URLError、ValueError 和 unknown error 有唯一预期。
- SourceError 经 business -> infra -> business 后没有字段、时区或 metadata 丢失。
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
| WF-001 | Spec validation、compiler、dataflow、cycle detection 和 runtime 共享一个 graph builder；fallback edge 是正式 graph edge，并保留 edge kind。 |
| WF-002 | `framework/llm/budget` 是 token/cost/call budget 唯一 owner；Agent/Workflow 只保留 tool/wall-time 等领域 adapter。 |
| WF-003 | Conversation message/cursor/checkpoint 和 memory vector document 归 owning port contract；framework/business 对 concrete store 使用显式 mapper，不依赖 structural typing 偶然兼容。 |
| WF-004 | 新 Harness-managed code 禁止依赖 legacy Agent/Workflow control-plane result；旧 exports 冻结，不新增调用方。 |
| WF-005 | 旧 WorkflowRunner/Agent subagent/budget 的删除必须先完成包外 import、动态入口、checkpoint/replay 和 persisted payload compatibility 审计。 |
| WF-006 | Framework fake 必须 domain-neutral；paper/reader-repair-specific fixture 移到 Research tests。 |
| WF-007 | 已确认不可达的私有 `_build_*`/`_legacy_build_*`、connector timeout/taxonomy wrapper 和薄 test-only facade 在回归覆盖后删除。 |

### 12.2 Acceptance

- fallback-only terminal workflow 可 strict compile 并按同一 graph 执行；fallback dataflow/cycle/max-visits 有测试。
- Canonical budget 对 router、Agent adapter 和 Workflow adapter 的 reserve/record/cost rounding 结果一致。
- AgentRunner -> LocalJson/Postgres conversation store，以及 MemoryIngestion -> vector store 完成真实 contract round-trip。
- 新生产代码对 legacy control-plane modules 的 import 数为 `0`。
- 删除清单中每个 public symbol 都附外部 consumer/replay evidence；无法确认的项保持 deprecated，不宣称安全删除。

---

## 13. 公共 API、数据与兼容矩阵

| Surface | 本阶段策略 | 允许变化 | 禁止变化 |
| --- | --- | --- | --- |
| Research HTTP/MCP | 保留现有 route/tool 名，替换默认 factory | unavailable error 可增加稳定 capability details | 成功 response envelope、analysis/reader/trace key 静默变化 |
| `/ask`/`/rag-ask` | 统一 service owner，保留显式 mode/alias | 增加 deprecation metadata、actor propagation | router singleton 和无 tenant filter 继续作为默认 |
| Approval store v1 | 保留 JSON fields 和 id | 修复 runtime type、validation、idempotency | 重写已有 approval id/status 或泄漏 secret |
| SourceError | 完整字段 round-trip | 恢复此前丢失字段 | 改变 error_type/retryable 历史语义而无 migration |
| Quality artifacts | canonical engine + compatibility mapper | 新增 engine version/reason codes | 删除已有 artifact keys、projection fields |
| Workflow checkpoint/events | 消费阶段 19 contract | graph semantics 修正 | 私自改 event/checkpoint schema 或 replay ordering |
| Conversation/vector data | mapper/port contract | 增加 validation | 无迁移改 persisted JSON/SQL/Qdrant payload |
| Skill experience | ref 变为可查询、hash 真实 | 增加 manifest/release metadata | 普通 run 自动 promotion |

---

## 14. OpenSpec 映射与 change 边界

### 14.1 复用 active changes

| Existing change | 本 PRD 使用范围 | 禁止扩展 |
| --- | --- | --- |
| `research-runtime-production-composition` | RES-001..006、RES-008 的 production factory、adapters、durable run store、transport parity、`/rag-ask` lifecycle/actor propagation 和 adapter boundary；新增范围必须先更新 design/tasks | 不顺手重写 Harness quality、Tool policy、Source 全局 policy |
| `framework-runtime-safety-hardening` | TOOL-004/007 的 unique built-in registration、composition safety；继续完成其 attempt/lease/error scope | 不在无 proposal 更新时加入 approval model、quality engine 或 Workflow graph 迁移 |
| `durable-event-runtime` | HAR-006、RES-008 所消费的 durable transcript/event/replay contract | 本 PRD 不修改 canonical event、outbox/inbox、sequence 或 replay engine |

### 14.2 建议新增 changes

| 顺序 | Change | Requirements | 说明 |
| --- | --- | --- | --- |
| 1 | `harness-deterministic-gate-enforcement` | HAR-001..007 | P1，落实既有 `harness-runtime` 唯一决策者契约，不重造状态机 |
| 2 | `tool-governance-canonicalization` | TOOL-001..006 | P1/P2；依赖 `framework-runtime-safety-hardening` 的 unique registration tasks 完成，避免并行改 composition |
| 3 | `source-policy-contract-convergence` | SRC-001..006 | 独立 contract change，可与 quality 批次并行 |
| 4 | `analysis-quality-contract-convergence` | QLT-001..005 | 先 parity，后 production cutover，再删旧算法 |
| 5 | `workflow-canonical-graph-semantics` | WF-001 | 聚焦 fallback/reachability/dataflow/cycle；保持 serialization/replay version compatibility |
| 6 | `research-experience-memory-provenance` | RES-007 | 独立于 production composition，修改 `harness-skill-evolution` experience/store/provenance contract |
| 7 | `framework-port-contract-convergence` | WF-002..003 | 先做 budget/conversation/memory contract audit，再分别迁移 canonical owner；不得建立 generic DTO god module |
| 8 | `framework-legacy-retirement` | WF-004..007 | 复用阶段 8/9 删除规则；只有在 production cutover 和外部 consumer/replay 审计后实施 |

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
| P0 | 将全部反例转为 failing regressions；归档/建立 OpenSpec；冻结 public contract snapshots | 无 | 每个 P1 至少一条修复前失败测试 |
| P1A | Harness gate authority | P0；阶段 19 gate-event schema 稳定 | Harness focused、deterministic replay、architecture、smoke |
| P1B | Approval canonical model、tool risk decision | P0；framework safety unique registration 完成 | Tool/store contract、全工具分类矩阵、smoke |
| P1C | Workflow canonical graph semantics | P0 | validator/compiler/runtime parity、serialization/replay compatibility |
| P2A | Source policy/mapper 收敛 | P0 | Source contract matrix、shared quota、round-trip |
| P2B | Quality parity、canonical cutover、compat adapter | P1A | Golden decision review、artifact/persistence compatibility |
| P3 | Research production composition 完成；boundary、ask、tenant、durability 和 experience 分批收敛 | P1A/P1B/P2A；active Research change | HTTP/MCP/CLI parity、restart/concurrency、no fake graph、experience lookup |
| P4 | Budget、port DTO、legacy freeze/delete | P1-P3；与 durable event 文件冲突解除 | Store contract、external import/replay audit |
| P5 | 全量回归、迁移/回滚演练、删除 compatibility window 到期项 | P1-P4 | mandatory smoke、strict OpenSpec、diff check、release evidence |

P1A、P1B、P1C 可以在 file ownership 不冲突时并行；P2A 与 P2B 可以并行。Research adapter 实现可以提前推进，但 P3 final cutover 必须等待 Harness authority、Tool governance 和 Source policy contract 稳定。P4 若触碰 event/checkpoint 文件，必须等待 `durable-event-runtime` 对相同文件的 owner 明确后再实施。

每个 change 至少独立提交：tests/spec -> implementation -> migration/cutover -> deletion/docs。禁止用一个提交同时完成跨 Tool、Source、Quality、Research、Workflow 的大规模移动。

---

## 16. 文件级影响矩阵

### 16.1 必须修改或明确 owner

| Area | 代表文件 | 目标变化 |
| --- | --- | --- |
| Harness VERIFY | `framework/harness/control_plane/harness.py`、`scheduler.py`、`routing.py`、`workflow/step.py` | named gate registry、gate-derived verdict、worker observation 隔离、durable gate identity |
| Research composition | `interfaces/api/app.py`、`interfaces/services/research_service.py`、`interfaces/services/mcp_service.py`、`interfaces/api/routers/research.py` | 统一 production factory、durable store、移除 route singleton、actor propagation |
| Research boundary | `business/research/services/rag_policy.py`、`application/paper_rag_session.py`、`application/single_paper_runtime.py`、`infrastructure/research/*` | 明确 designated runtime/adapter boundary、精确 port/DTO imports、experience store/provenance |
| Tool governance | `framework/tool/governance/approval.py`、`framework/workers/approval/model.py`、`framework/tool/models/policy.py`、framework/infra/business catalogs | canonical approval DTO 与 risk decision，registry 只追加 inventory |
| Source policy | business Source normalization/runtime/health、`infrastructure/external/sources/fetch_policy.py`、interface mappers | URL/retry/taxonomy/limiter/mapper 单一 owner |
| Quality | `business/layers/analysis/quality_records.py`、`analysis/quality/*`、`analysis/tools.py`、Research quality adapter | canonical engine、shadow parity、compatibility mapper、旧算法退出 |
| Workflow/contracts | specs validation、workflow compiler/runtime、LLM/Agent budget、conversation/memory models | canonical graph 与 port-owned contracts；legacy freeze |

### 16.2 必须新增或扩展的测试区域

| Test area | 覆盖 |
| --- | --- |
| `tests/framework/harness` | named gate binding、worker score isolation、gate event/replay、budgeted failure handling |
| `tests/framework/tool` + approval stores | model identity、backend lifecycle、risk matrix、side-effect-before-approval invariant |
| `tests/interfaces/research` + `tests/infrastructure/research` | configured object graph、transport parity、actor/tenant、restart/concurrency、adapter allowlist |
| Source business/infra/interface tests | golden URL、taxonomy/retry、shared quota、mapper round-trip |
| Analysis quality tests | shared golden corpus、shadow diff classification、engine identity、persisted payload decode |
| Workflow/storage contracts | fallback graph parity、budget parity、conversation/vector backend conformance |

### 16.3 不应顺手修改

- 阶段 18 已完成的 artifact integrity/path/checksum 设计，除非新增 contract test 证明本阶段造成回归。
- 阶段 19 的 canonical event、outbox/inbox、sequence、replay、SQLite/PostgreSQL event store 和 OTel/W3C 设计。
- Parser/RAG backend 算法、frontend/UI、multi-host scheduler、distributed Source limiter 或新增 source provider。
- 与当前 change 无关的 public API、OpenAPI schema、数据库迁移和生成文件。

---

## 17. 测试计划与 Requirements -> Tasks -> Tests 追踪

| Requirements | Task/change | 必须测试 | 关键 oracle |
| --- | --- | --- | --- |
| HAR-001..007 | `harness-deterministic-gate-enforcement` | worker forbidden fields、unknown gate、step/global gate selection、LLM score routing、replan budget、transcript replay | verdict 只引用 deterministic gate result；未知 gate 时 `worker_calls=0` |
| RES-001..006、008 | `research-runtime-production-composition` completion | configured/unavailable object graph、六类 transport parity、restart、concurrent runs、tenant visibility | 无 fake/unconfigured/in-memory production dependency；50-run isolation 串扰为 0 |
| RES-007 | `research-experience-memory-provenance` | experience append/query、real package hash、gate failure/no-promotion | ref 可查询；普通 run promotion count 为 0 |
| TOOL-001..007 | `tool-governance-canonicalization` | type identity、InMemory/LocalJson/Postgres contract、duplicate decision、risk golden matrix、registry partition、Harness approval | 所有入口同一 decision；side effect 在 durable approval 前为 0 |
| SRC-001..006 | `source-policy-contract-convergence` | URL golden corpus、retry/status matrix、cross-entry limiter、taxonomy、mapper round-trip、connector factory | 相同 input 得到相同 identity/retry/quota/error payload |
| QLT-001..005 | `analysis-quality-contract-convergence` | old/new parity snapshot、production/eval identity、Research adapter、artifact/persistence projection、100-run determinism | `unclassified_diff_count=0`；一个生产算法 owner |
| WF-001 | `workflow-canonical-graph-semantics` | fallback-only、cycle/dataflow、read_keys、compiler/runtime route parity | 三层 graph semantic disagreement 为 0 |
| WF-002..003 | `framework-port-contract-convergence` | budget parity、conversation/vector backend conformance | persisted contract 不变；structural-typing-only path 为 0 |
| WF-004..007 | `framework-legacy-retirement` | AST/import/export、dynamic entry、replay fixture、legacy metric | 未确认 public consumer 的 symbol 不删除；undocumented compatibility 为 0 |
| Architecture | 各 change architecture batch | AST/import rules、composition owner、framework domain neutrality、legacy freeze | 禁止规则精确，无 blanket ignore |
| Optional live | release qualification | credential-gated arXiv/LLM、Redis/Postgres/Qdrant conformance | ordinary smoke 不依赖 live；live failure 与代码失败分开报告 |

测试不得只断言源码包含某个字符串或 factory 名称。Boundary tests 应使用 AST/import graph；composition tests 应检查真实对象图和行为；backend tests 应复用参数化 contract suite，同时保留各 backend 的事务/SQL/锁断言。

---

## 18. 验证命令

每个 change 运行自身 focused suite；阶段级 release gate 至少包含：

```powershell
openspec validate --all --strict
python -m scripts.dev compile
python -m scripts.dev smoke
git diff --check
```

如果 change 修改 PostgreSQL、Redis、Qdrant 或 live transport adapter，必须额外运行其 backend contract suite，并记录依赖缺失、credential skip 和真实代码失败的区别。不得用新增 `skip/xfail` 关闭本 PRD 的 regression。

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

### 20.2 回滚条件

| 条件 | 回滚动作 |
| --- | --- |
| Gate registry 误拒合法 workflow | 回滚 registry mapping/version，不恢复 worker score verdict |
| Research factory 配置导致启动不可用 | 回到 typed unavailable service，不回到 fake/in-memory success path |
| Tool risk cutover 阻断合法 read-only tool | 修正 canonical decision/golden case；高风险默认仍 fail-closed |
| Source policy 造成请求激增或误限流 | 回滚 composition binding并保留共享 limiter，不复制 limiter |
| Quality canonical engine 改变外部 payload | 回滚 compatibility mapper/cutover，保留 parity evidence和新 engine |
| Workflow graph 修正影响历史 checkpoint | 保留历史 reader/upcaster，停止新 graph cutover，不改写历史记录 |

---

## 21. 风险与对策

| 风险 | 对策 |
| --- | --- |
| PRD 范围过大形成 mega change | 强制按第 14/15 节拆分 OpenSpec 与 commit；P1、Research、Source、Quality、Workflow 独立验收 |
| 将有意 backend/domain 变体误删 | 删除前执行 ownership、I/O lifecycle、external import、persisted contract 四项复核 |
| Quality 新实现更严格导致大量 report 被拒 | 先运行 shadow parity/golden review，再切 production；不通过降低 gate 阈值掩盖差异 |
| Architecture allowlist 变成逃生口 | 只允许精确 module/type，禁止目录级/前缀级 blanket exception |
| Active OpenSpec 并行修改相同文件 | 每个 change 声明 file owner；Research、安全、event 三个 active change 先做 overlap check |
| 删除 public legacy export 破坏包外消费者 | 一个 release deprecation、usage telemetry/import audit、migration note 后再删 |
| Live Redis/Postgres/Qdrant 与 fake 行为不同 | contract suite + optional real-service CI；缺依赖/凭据单列环境盲区 |
| 修复 Source/Tool policy 时引入新的共享 god module | contract 放 owning domain；adapter 保持薄；禁止无 owner generic utils |

---

## 22. Definition of Done

### 22.1 P1 authority

- [ ] Worker output 不能直接形成 Harness quality verdict 或 route。
- [ ] 所有 step quality gates 可解析、可执行、可 replay；未知 gate fail-closed。
- [ ] 默认 configured Research HTTP/MCP/CLI 进入真实 runtime 和 durable store。
- [ ] Tool approval 使用唯一 canonical worker model，重复 decision 在所有 store 中一致拒绝。

### 22.2 Contract convergence

- [ ] Tool risk classification 在 discovery/schema/executor/inspection/Harness 中一致。
- [ ] Source URL、limiter、retry、taxonomy 和 mapper 各只有一个决策 owner。
- [ ] Production/eval 通用 quality 规则使用同一 engine。
- [ ] Workflow validation/compiler/runtime 使用同一 graph semantics。
- [ ] LLM budget、conversation 和 memory document 不再依赖重复 DTO 的 structural typing。

### 22.3 Boundaries and compatibility

- [ ] `business/research` 不依赖 legacy、interfaces 或 infrastructure；普通 application/service 不分散构造 Harness controller，指定 runtime boundary 只依赖获批的 domain-neutral contract。
- [ ] `infrastructure/research` 只依赖精确获批的 Research domain/port contract，architecture smoke 通过。
- [ ] HTTP/MCP/SDK、approval JSON、quality artifacts、SourceError、event/checkpoint 和 storage payload compatibility 有 committed tests。
- [ ] 每个 compatibility adapter 有 owner、删除条件和期限。

### 22.4 Delivery evidence

- [ ] 所有建议 change 通过 `openspec validate <change> --strict`。
- [ ] `openspec validate --all --strict`、`python -m scripts.dev compile`、mandatory `python -m scripts.dev smoke` 和 `git diff --check` 全部通过。
- [ ] Optional live Redis/Postgres/Qdrant/arXiv/LLM 结果与 ordinary offline gate 分开记录。
- [ ] 删除清单附 `rg`/import graph、包外 consumer、dynamic entry、persisted replay 和替代测试证据。
- [ ] PRD、OpenSpec tasks、tests 和 implementation commits 建立 requirements traceability。

阶段 20 只有在上述条件全部满足时才能标记 `FINAL / IMPLEMENTED`。局部 change 完成不得用于宣称整个阶段已收敛。

---

## 23. 可复制给 Codex 的实施提示

实施任一阶段 20 change 时，Codex 必须：

1. 只读取本 PRD 中该 change 对应的 requirement、owner、兼容矩阵和测试 oracle，不把 umbrella scope 一次性实现。
2. 先执行 live repro 并提交 failing regression，再修改 production code。
3. 读取 active OpenSpec/file ownership，避免与 Research、framework safety、durable event 并行 change 修改同一 contract。
4. 使用 canonical owner 和显式 adapter，不新增第二套 policy、DTO、graph、store 或 compatibility path。
5. 完成 focused tests、architecture tests、strict OpenSpec、compile、mandatory smoke 和 diff check 后再提交。
6. 删除 legacy 前附 production/dynamic/public-export/persistence/replay 证据；证据不完整时保留并登记 expiry，不猜测安全删除。
