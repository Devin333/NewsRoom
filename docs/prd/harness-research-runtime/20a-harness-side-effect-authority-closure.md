# 阶段 20A：Harness 副作用授权与 Research 发布一致性闭环 PRD

> Document status: READY_FOR_IMPLEMENTATION
>
> Implementation status: IN_PROGRESS（当前工作树快照，不代表已发布）
>
> Version: v1.2
>
> Priority: P1（控制权、数据可见性与恢复正确性）
>
> Parent: 阶段 20《框架边界与重复实现收敛》
>
> OpenSpec: `harness-side-effect-authority-closure`
>
> Baseline: `HEAD 14ce76bf` 加当前 dirty working tree；当前任务台账为 `49/51`，未提交修改不作为发布证据
>
> Last updated: 2026-07-20

## 0. 一句话结论

把所有 Harness 管理的外部可见写入收敛到一条可审计、fail-closed、可恢复的权威链路：

```text
candidate -> deterministic VERIFY -> durable authority -> idempotent effect
-> durable outcome -> successful transition
```

Research 的 artifact、trace、transcript 和 run record 必须遵循同一条链路；失败结果可以保留为诊断，但不得进入 canonical、published 或 latest 视图。

## 1. 背景与问题

### 1.1 为什么现在做

专项审查发现，Harness 已经拥有 `PLAN -> EXECUTE -> VERIFY`、预算和 durable transcript 的基础能力，但副作用边界仍有三类实际缺口：

1. worker 结果曾允许通过嵌套字段或别名表达 publication、promotion、authorization、memory write 等决策；这些字段不应成为可执行事实。
2. Research 的 `publish_artifacts` 在 worker 的 `EXECUTE` 阶段直接写 canonical artifact，`publish_requires_verify` 只有配置语义，没有完整的运行时提交协议。
3. Research 失败 run 与成功 run 共用 latest 选择语义，失败结果可能遮蔽上一次 accepted 结果；skill release 也必须防止普通 run 或伪造 promotion object 直接修改 active version。

### 1.2 当前证据与边界

| 观察 | 证据 | 当前结论 |
| --- | --- | --- |
| worker ingress 已有递归保留字段校验和 typed `effect_intent` 结构 | `framework/harness/workers/result.py:84-180` | contract slice 已实现，并已由 control plane 的 exact-handler authority 路径消费 |
| control plane 已接入 preflight binding、worker/controller-terminal authorization 与 decision/outcome ordering | `framework/harness/control_plane/harness.py:475-530,822-960,1446-1587` | focused authority/recovery/store 与完整 Harness 已通过；mandatory smoke 为 `1427 passed` |
| durable recovery 已覆盖 dangling decision、SQLite restart、scope mismatch 和 terminal retry exhaustion | `tests/framework/harness/control_plane/test_side_effect_authority.py:361-1025`；`tests/framework/harness/control_plane/test_side_effect_durable_recovery.py:209-512` | 原 terminal parity blocker 已修复；stale MCP fake caller 已迁移为 observation，完整 Harness 为 `492 passed` |
| Research worker 已改为 typed bundle intent，handler 在 hidden candidate path prepare，并由 terminal intent 提交单一 manifest 可见性 | `business/research/application/single_paper_runtime.py:1213-1352`；`infrastructure/research/artifact_publication.py:81-378`；`tests/business/research/integration/test_research_artifact_publication.py` | artifact/publication focused matrix 已通过；VERIFY 失败、Nth-member 失败、effect-id 幂等和 cleanup 隔离均有回归 |
| workflow 与 composition 已绑定 exact handler、terminal policy、SQLite side-effect store、v2 run store 和 reconciler | `business/research/workflows/paper_analysis_workflow.py:106-136`；`interfaces/composition/research.py:527-1195` | dual reader/v2 writer、startup/lazy reconciliation 和 scope-bound diagnostic reader 已接入；部署顺序与 staged release 仍待交付门禁 |
| skill release contract 已有 provenance resolver，且 fake/registry 标记为非生产 | `framework/harness/skills/evolution/authority.py:36-174`；`framework/harness/skills/evolution/release.py:24-82` | 只计入 contract evidence，不宣称生产 release store 已接入 |
| Research disposition/store 合同与 recovery composition 已落地 | `business/research/application/run_disposition.py:94-260`；`infrastructure/research/filesystem_run_store.py:143-215`；`interfaces/services/research_service.py:229-700`；`interfaces/composition/research.py:527-1195` | v1/v2 strict reader、legacy quarantine、accepted-only latest、startup/lazy recovery 和异常落库 focused matrix 已通过；仍需 broad/smoke/staged release evidence |
| OpenSpec change 当前已完成实现任务主体，交付任务仍开放 | `openspec/changes/harness-side-effect-authority-closure/evidence.md:231-520`；`tasks.md:1-71` | `49/51` 是当前工作树进度，不是 release 状态 |

本 PRD 不接管 `framework/events/schema/catalog.py`、generic Tool/Workflow、Redis worker queue、MCP/OpenAPI 或其他 active change 的 ownership。它们只通过既有 port、projection 和事件契约协作。

## 2. 用户、角色与关键场景

### 2.1 目标角色

| 角色 | 需要的结果 |
| --- | --- |
| Harness workflow author/operator | 能声明 exact handler、gate、budget、approval 和 terminal policy，并得到可复盘的授权记录 |
| LLM、subagent、candidate worker | 只能提交候选 intent、observation、diagnostics 和候选引用，不能取得 commit port 或决定流程 |
| Research 业务用户 | `get_analysis`、`get_reader`、`ask_paper` 始终读取 accepted latest，不被失败 run 污染 |
| Research 运维/审计人员 | 能按 run 和 scope 查看 quarantine、trace、transcript，并安全执行 recovery/replay |
| Skill evolution owner | 只能发布通过 candidate、held-out eval、gate、approval、版本和 rollback 绑定的 skill |
| 迁移/发布负责人 | 能先部署 dual reader，再启用 v2 writer，并在任一阶段保留可回滚路径 |

### 2.2 核心场景

1. **正常提交**：worker 产出 typed candidate，deterministic gate 通过，Harness 记录 authority，handler 幂等提交 outcome，随后才推进 step/run success。
2. **gate 或 approval 失败**：不调用 effect handler；候选被保留为非公开诊断或 quarantine。
3. **中途崩溃**：在 decision、effect、outcome 或 transition 任一边界重启，最多恢复同一个 effect identity，不重复已提交效果。
4. **Research 失败跟随成功**：失败 run 可按 run id 诊断，但 accepted latest、正常分析、reader 和 ask 仍指向之前成功 run。
5. **Research 终态发布**：隐藏准备的 artifact、trace 和 transcript 由一个 controller-terminal intent 原子提升到公开视图；任一成员失败都不产生新的公开组。
6. **普通 run 触发 skill promotion**：active skill、release history 和 rollback 状态写入次数必须为零。

## 3. 产品目标与成功指标

### 3.1 目标

- **G1 唯一权威**：quality、routing、authorization、publication、memory write 和 skill promotion 的决定来自 Harness 的确定性控制面。
- **G2 先授权后效果**：任何受管副作用都必须有 durable decision；成功状态必须引用可按 scope 回读验证的 durable outcome。
- **G3 可见性隔离**：`candidate`、`prepared`、`quarantine`、`accepted` 和 `latest` 各有明确 namespace 与查询边界。
- **G4 恢复可证明**：recovery/replay 使用记录中的 identity、ordinal、causation 和预算；offline replay 不调用 worker 或 effect port。
- **G5 兼容优先**：保留公共 Research response、artifact URI/payload、既有事件 envelope 和历史 v1 record 的读取能力。
- **G6 ownership 清晰**：本 change 只收敛 Harness authority、Research publication/disposition 和 skill contract，不复制其他 owner 的 policy 或 adapter。

### 3.2 可量化成功指标

| 指标 | 目标 |
| --- | --- |
| gate failed、approval pending/cancelled、scope mismatch、budget exhausted 时的 effect handler 调用 | `0` |
| decision-before-effect、outcome-before-success 顺序违规 | `0` |
| crash/restart 中重复的 effect identity | `0`；同一 identity 必须幂等复用 |
| offline replay 对 worker、handler、memory、artifact、Tool、MCP、release port 的调用 | `0` |
| 正常 Research query 返回 quarantine run 的比例 | `0` |
| 第 N 个 artifact 成员失败后新增 canonical manifest/index 条目 | `0` |
| 无明确 Harness evolution authority 时 active/release/history 写入 | `0` |
| v1 record dual-read 的字节改写 | `0` |

## 4. 范围与非目标

### 4.1 范围

- worker-result 递归保留字段拒绝、单一 typed side-effect intent 和候选引用校验。
- step exact handler、terminal policy、preflight binding、authorization、approval/scope/budget 检查。
- durable decision、idempotent handler、outcome read-back、quarantine、retry exhaustion、dangling decision recovery 和 offline replay。
- Research v2 disposition、v1/v2 dual reader、accepted-only latest、失败诊断、启动/懒惰 reconciler。
- Research hidden artifact preparation、controller-terminal atomic publication、trace/transcript 与 accepted manifest/index 的一致性。
- provenance-bound skill release contract；仅在明确生产 owner 接入后才可宣称生产发布。

### 4.2 非目标

- 不替换 Harness scheduler、`PLAN -> EXECUTE -> VERIFY` 状态机、既有 gate registry 或 durable event runtime。
- 不定义 generic Tool risk classification、Tool approval store、生产 ToolRegistry 或 MCP policy。
- 不宣称 generic Harness Memory、AgentLoop、Workflow Tool runner、Reader Repair effect 已完成生产接入。
- 不让普通 Research run 直接更新 memory、active skill 或 publication。
- 不替换现有 RAG bounds、Reader Repair gate、artifact path/checksum owner。
- 不实现跨外部服务的分布式事务或全局 exactly-once；本 PRD 只要求 durable identity、幂等 handler 和单一公开可见性提交。
- 不以兼容层为理由永久保留已被唯一实现取代的 legacy code；删除必须另有调用方、动态入口和 replay 证据。

## 5. 领域状态与系统不变量

### 5.1 副作用状态

| 状态 | 含义 | 可见范围 | 允许的下一步 |
| --- | --- | --- | --- |
| `candidate` | worker 产生、尚未授权的数据或引用 | worker activity、受限诊断 | `prepared`、`quarantine` |
| `prepared` | handler 已生成隐藏候选，未进入 canonical/index | run-scoped hidden namespace | `accepted`、`quarantine`、过期清理 |
| `quarantine` | 失败、取消、阻塞、过期或证据不足的结果 | explicit diagnostic query | 只允许诊断、清理或人工复核 |
| `accepted` | 通过 deterministic gate、scope、authority 和完整性检查的结果 | canonical/published read path | 更新该 subject 的 `latest` |
| `latest` | accepted records 的查询投影 | normal analysis/reader/ask | 只能由新的 accepted record 替换 |

`quarantine` 永远不能替换 `latest`；没有任何 accepted record 时，正常 latest 查询返回明确的 not-found/unavailable，而不是返回 quarantine。

### 5.2 不变量

1. worker 是 candidate producer，不是 workflow、quality、authorization 或 publication owner。
2. deterministic VERIFY 是副作用授权的必要条件；worker output、self-score 或 observation 不能绕过 gate。
3. decision 必须先 durable，effect 才能执行；outcome 必须先 durable/read-back，step/run 才能成功。
4. retry 和 replan 生成新的 attempt/effect identity；旧 approval 不能授权新 candidate。
5. scope、handler、kind、intent、gate、approval、budget、decision 和 outcome 任一 checksum 不匹配都 fail closed。
6. replay/rebuild/verify 只读取记录，不重新调用 live worker 或 effect。
7. 事件 envelope、schema catalog 和既有公共 DTO 仍由其原 owner 维护。

## 6. 目标架构与运行路径

### 6.1 Harness worker-side effect

```mermaid
flowchart LR
    A[Worker candidate] --> B[Recursive ingress validation]
    B --> C[PLAN and deterministic VERIFY]
    C -->|fail or pending| Q[Quarantine or waiting state]
    C -->|pass| D[Durable side-effect decision]
    D --> E[Exact registered handler]
    E --> F[Durable outcome and scoped read-back]
    F --> G[STEP_SUCCESS or COMPLETE_RUN]
    D -. crash recovery .-> E
    G --> H[Replay reads history only]
```

每个 step 最多一个 typed intent；多个 effect kind、handler 或 atomic group 必须拆成显式 workflow step。handler registry 为实例级，不使用 module-global mutable registry。

### 6.2 Research production path

```text
source collection -> evidence -> agent analysis -> report/quality
-> hidden artifact preparation (prepared)
-> all step outcomes durable
-> controller-terminal authorization
-> one atomic publication of artifacts + trace + transcript + accepted manifest/index
-> accepted run record -> latest projection
```

terminal intent 绑定 run、terminal policy、state checksum、completion input、scope、prepared outcome refs、history cutoff 和 exact handler。`COMPLETE_RUN` 只有在 terminal outcome 可回读后才能持久化。

## 7. 详细功能需求

### HAR-001：Worker ingress 只能表达候选

- `output`、`diagnostics`、`metrics` 递归拒绝 route、verdict、approval、authorization、memory commit、publication、promotion、active release 等未类型化决策别名。
- `*_observation` 字段可以保留，但永远不参与 authority algorithm。
- `effect_intent` 必须是单一、typed、immutable 的 `HarnessSideEffectIntent`；domain payload 内同名字段不能获得授权含义。
- `artifacts` 只接受严格 candidate reference，不因 worker 成功而自动提升为 accepted ref。

**验收**：直接、嵌套、alternate、diagnostics、metrics 矩阵全部拒绝；合法 observation 和 typed domain payload 通过；多 intent、handler/kind 不匹配在调度前拒绝。

### HAR-002：Preflight 绑定唯一 handler

- `HarnessStepSpec` 必须声明 exact versioned handler reference；缺失、未知、重复、版本不支持或 kind 冲突在 `RUN_CREATED` 前失败。
- terminal side effect 使用 versioned `HarnessTerminalSideEffectPolicy`，缺失 policy 的历史 run 仅允许离线 replay；需要 live recovery 时 fail closed。
- production worker 不得持有 concrete artifact、memory、release 或 commit store。

**验收**：非法 workflow 不产生 worker call、decision 或 effect side effect；同一 instance 的 registry 不受 import order 影响。

### HAR-003：授权只来自确定性证据

- authority 必须同时绑定当前 run/step/attempt、worker activity、声明的 handler/kind、所有 required VERIFY gate、aggregate verdict、budget 和 scope。
- approval 必须由注入的 read-only evidence resolver 验证 run、step、attempt、effect id、candidate checksum、identity scope、subject scope 和 decision version。
- worker status、worker score、裸 boolean 或 caller-created decision 不得产生授权。

**验收**：gate fail、approval pending/cancelled、scope mismatch、budget exhausted 均不调用 handler；旧 attempt approval 不能授权 retry/replan。

### HAR-004：Decision、effect、outcome 顺序固定

- 先持久化 canonical authorization，再调用 exact handler。
- handler 必须持久化 typed outcome；Harness 必须 scoped read-back 校验 effect、decision、handler、idempotency、disposition 和 checksum。
- read-back 失败时不得推进 `STEP_SUCCESS`、下游 routing 或 `COMPLETE_RUN`。

**验收**：四个 crash boundary（decision 前、decision 后、effect 后/outcome 前、outcome 后/transition 前）均可重启验证，成功状态不会早于 outcome。

### HAR-005：有界恢复与只读 replay

- dangling decision 只能有一个精确匹配；恢复复用原 ordinal、causation、effect id 和 scope。
- 已有 matching outcome 时不再调用 handler；没有 outcome 时只在持久化 retry budget 内重试。
- 多个或冲突 decision、checksum 漂移、retry exhaustion 进入稳定非成功状态。
- offline replay/rebuild/verify 不调用 worker、handler、memory、artifact、Tool、MCP 或 release port。

**验收**：SQLite durable store 和 in-memory contract 覆盖 restart、scope isolation、idempotency、retry exhaustion、multiple dangling decision 和 replay zero-call。

### HAR-006：候选、隔离和公开可见性分层

- candidate/prepared 使用 run-scoped hidden namespace；cancel、halt、failed、blocked、approval-waiting、superseded 和过期候选进入 quarantine 或清理。
- 只有 accepted record 可以写入 canonical/published/latest projection。
- 所有 disposition 带有可审计 reason、scope、retention 和关联 refs。

**验收**：quarantine record 可按 run 查询但不出现在 normal analysis、reader、ask、latest 或 publication endpoint。

### RES-001：Research disposition 与 latest isolation

- disposition 由 terminal status、quality evidence、publication/artifact authority、identity scope 和完整性证据 fail-closed 推导。
- `save(record)` 仍是 application boundary；by-run 读取保留诊断，latest/list normal path 只选择 accepted。
- v1 record 不改写原字节；缺失、共享 root、scope 冲突或 manifest 证据不足统一 quarantine。

**验收**：accepted run 后写入 failed/quarantine run，进程内、重启后和 mixed-version index repair 仍返回 accepted latest；只有 quarantine 时 normal query 明确无 accepted 结果。

### RES-002：Research hidden preparation 与终态原子发布

- `publish_artifacts` 改为 typed atomic bundle intent，使用 hidden candidate paths 和 prepared outcome。
- 第 N 个成员失败时不产生新的 canonical manifest/index visibility；候选由 owner 清理或 quarantine。
- terminal handler 在所有 step outcome durable 后，一次性发布 artifact group、trace、transcript 和 accepted manifest/index；public refs 来自 terminal outcome，不改变 URI/payload contract。
- v2 normal reader 必须同时绑定 run、identity scope、subject scope、publication authority、artifact evidence 和成员 content checksum；仅匹配 accepted 状态或可重算 manifest hash 不足以授权读取。
- published trace 固定截止到 terminal authorization 的 committed-history cutoff；之后的 outcome 与 `COMPLETE_RUN` 仍保留在 canonical durable event history，不能通过改写已发布 trace 形成自引用 checksum。

**验收**：取消、gate failure、terminal handler failure 和 crash recovery 均保持全有或全无；恢复复用原 terminal effect id，不重复 worker 或 artifact effect。

### RES-003：Reconciler 关闭 terminal crash window

- 处理 durable terminal completion 后、accepted Research record 保存前的进程崩溃。
- startup/lazy reconciliation 只依据 durable history、terminal outcome、artifact evidence 和 scope 重新分类。
- reconciler 必须幂等，不调用 worker 或 effect handler。

**验收**：重启后 accepted 和 quarantine 的分类稳定，重复执行不产生新 publication 或 index entry。

### SKL-001：Skill release 只能使用 provenance-bound authority

- release authority 必须绑定 canonical candidate、held-out evaluation、promotion gate、approval、package hash、release version、rollback plan、side-effect decision 和 idempotency refs。
- registry 在第一次写 release/history/active version 之前解析 authority；伪造或篡改对象零写入失败。
- fake contract 明确 `production_ready = False`；普通 Harness/business run 不得激活 skill。

**验收**：ordinary run、caller-created approved-looking decision、unregistered authority、candidate/version/package/rollback tamper 均使 release、history、active writes 保持 `0`；合法发布和回滚幂等。

## 8. API、数据与兼容性要求

| 领域 | 兼容要求 |
| --- | --- |
| Research HTTP/MCP/SDK | 保持现有成功响应字段、错误分类、trace 字段和 run-id 查询形状；quarantine 通过显式诊断 contract 暴露 |
| Artifact | 保持既有 URI、payload、checksum 和 reference 语义；新增 hidden/prepared 状态不得泄漏为 public ref；v2 manifest 与 accepted run disposition 必须完成 scope/authority/evidence/member checksum round-trip |
| Event/history | 复用现有 envelope、event type、`HARNESS_DECISION_INPUT_SCHEMA` 和 safe projection 槽位；不修改 `framework/events/schema/catalog.py`；published trace 是 terminal cutoff 投影，durable event history 是完整 replay source |
| Workflow | 未声明 side-effect policy 的历史 payload 序列化结果保持兼容；legacy offline replay 不凭空生成 terminal effect |
| Research persistence | v1/v2 dual-read；v1 bytes 不重写；v2 writer 必须在 dual reader 部署并验证后启用 |
| Skill release | 旧 unbound DTO 可以只读解析，但任何 active mutation 都必须有新 authority |

任何公共 API、持久化格式或事件 schema 的突破性变更都必须另开 OpenSpec change，不在本 PRD 内偷偷兼容。

## 9. Ownership 与依赖边界

| 能力 | 唯一 owner | 本 PRD 的关系 |
| --- | --- | --- |
| Harness authority、side-effect contracts、recovery | `framework/harness` | 本 PRD 交付 |
| Research disposition、artifact preparation、terminal publication | `business/research` + `infrastructure/research` ports/adapters | 本 PRD 交付；业务层不得反向依赖 concrete infrastructure |
| Durable event envelope/schema/delivery | `framework/events` 及其 active change | 只消费既有 projection/ref，不转移 ownership |
| Tool risk/approval canonical model | `framework/tool` governance owner | 通过 read-only approval evidence port 集成，不复制 DTO/store |
| Skill evolution contract | `framework/harness/skills/evolution` | 本 PRD 只收敛 provenance authority；生产 store 需另有 composition evidence |
| HTTP/MCP/CLI interface | `interfaces` application service | 只调用 Research application service，不直接访问 executor/store |
| Redis/Postgres/Qdrant 等真实 backend | 各自 infrastructure owner | 本 PRD 不运行 live E2E，不用 fake 代替生产资格 |

依赖顺序固定为：

```text
research-runtime-production-composition archive
-> dual readers and v1/v2 compatibility
-> Harness authority contracts
-> control-plane decision/outcome recovery
-> hidden Research preparation
-> terminal atomic publication
-> accepted latest cutover
-> broad smoke and staged-only release
```

## 10. 测试与验证计划

### 10.1 行为测试矩阵

| 测试层 | 必须覆盖 |
| --- | --- |
| Worker contract | reserved aliases、nested paths、observations、typed payload、candidate refs、one-intent invariant |
| Authority/control plane | gate/approval/scope/budget、retry/replan、新 attempt、decision/outcome ordering、terminal policy |
| Durable store | SQLite WAL/FULL、restart、idempotency、scope isolation、multiple dangling decisions、retry exhaustion |
| Research store/service | accepted-only latest、failed diagnostics、v1/v2 dual-read、index repair、service reconstruction、error ordering |
| Artifact publication | hidden preparation、N-th member failure、cancel/expiry、terminal atomic group、trace/transcript cutoff、public ref provenance |
| Skill evolution | ordinary run、forged authority、tampered provenance、publish/rollback idempotency、zero writes |
| Architecture | business/interface/infrastructure direction、worker no concrete commit port、excluded owner boundaries |
| Compatibility | API/MCP/CLI response shape、legacy payload/checksum、offline replay zero-call |

### 10.2 必须执行的门禁

```powershell
openspec validate harness-side-effect-authority-closure --strict
openspec validate --all --strict
.\.venv\Scripts\python.exe -m scripts.dev compile
.\.venv\Scripts\python.exe -m scripts.dev smoke
git diff --check
```

真实 Redis/Postgres/Qdrant、live arXiv/LLM 和 live credential E2E 不在本 PRD 的本地门禁内，必须在发布记录中明确标注为 residual external-service limit。

当前可重放的 working-tree evidence 包括 Harness authority/skill/replay `173 passed`、完整 Harness `492 passed`、Research/store/artifact/composition `383 passed, 2 skipped`、HTTP/MCP/SDK `51 passed`、recorded transport `2 passed`、相关 architecture `17 passed`，以及四项 failure-recovery regression `4 passed`。baseline 已按顺序归档，OpenSpec strict 全仓 `510/510`，mandatory smoke `1427 passed, 23 deselected`。当前仅 staged-only release 和最终提交 evidence 未完成，因此尚不能转为 implemented。

## 11. 发布、迁移与回滚

### 11.1 发布顺序

1. 先完成 `research-runtime-production-composition` 的归档/基线确认和现有调用方审计。
2. 部署并验证 v1/v2 dual readers、mixed-version repair 和 quarantine diagnostics。
3. 启用 v2 disposition writes；旧 v1 bytes 保持只读。
4. 发布 Harness decision/outcome/recovery contract，先在 shadow/fake handler 验证，再绑定 Research handler。
5. 切换 Research hidden preparation 和 controller-terminal publication；停用 worker EXECUTE 的 canonical writes。
6. 完成 accepted-only latest、trace/transcript atomic visibility、reconciler 和 restart 验证。
7. 最后完成 skill release authority 的生产 composition 资格审查；contract fake 不可替代该门禁。

### 11.2 回滚原则

- dual reader 部署前可以停止新 writer，保留旧 writer 和 staging candidate。
- dual reader 部署后不能回滚到无法读取 v2 的版本；可以回滚 writer 开关，但保留 v2 schema 和 quarantine bytes。
- terminal decision 已 durable 后不得回到 memory-only success；恢复必须复用原 effect identity。
- accepted record 不因回滚降级为 quarantine；需要修复时写入新的 scoped diagnostic 或 accepted replacement。
- 删除 legacy/compat 前必须通过仓内 import、动态入口、公共 API、持久化回放和外部 consumer 审计。

## 12. 风险与未决问题

| 风险/问题 | 处理门 |
| --- | --- |
| 递归 reserved-key 可能误伤合法领域字段 | 以 versioned matrix、explicit observation 命名和 domain payload opaque 规则锁定；不得静默丢字段 |
| candidate worker 通过隐藏依赖执行 I/O | composition/architecture test 检查 concrete port closure 和调用计数 |
| event schema 不允许新增 side-effect 专属字段 | 仅使用既有 safe projection/ref 槽位；需要 schema 变更时另开 owner change |
| terminal state checksum 在内存与恢复 projection 间漂移 | 增加 canonical durable projection parity golden cases；不能放宽 parity 比较 |
| `infrastructure/research -> business` 反向 import | 通过 domain port/mapper 修正；不能只扩大 architecture allowlist |
| v2 artifact resolver 未绑定 subject scope 或 artifact evidence | normal read 必须校验 manifest 与 accepted record 的 run/identity/subject/authority/evidence/member checksum 全量关联，并覆盖重算 manifest hash 后的篡改拒绝 |
| legacy MCP fake 使用 reserved `policy_decision` | 已做最小 caller migration 为 `policy_observation`；不改 MCP/Tool policy 或生产 adapter |
| 外部服务和生产凭据不可用 | 记录 residual limit；不得用 fake 结果宣称 production readiness |
| Research v1 manifest 证据不足或 scope 冲突 | fail closed quarantine，不改写历史 bytes |

## 13. Definition of Done

- [x] 所有 HAR/RES/SKL 需求都有对应 OpenSpec task、failing oracle、green regression 和 evidence 链接。
- [x] 所有受管 side effect 都遵循 `decision -> effect -> durable outcome -> success`，并通过 crash/restart 矩阵。
- [x] offline replay/rebuild/verify 的 live worker/effect call count 为 `0`。
- [x] Research hidden candidate、terminal atomic group、accepted-only latest 和 quarantine query 在进程内、重启和 mixed-version 下行为一致。
- [x] v1/v2 dual reader 在 v2 writer 前部署并验证，rollback target 仍可读取两种版本。
- [x] ordinary run 和伪造 skill promotion 对 active/release/history 的写入为 `0`；合法 authority 路径幂等。
- [x] architecture/import boundary、focused suites、compile、mandatory smoke、strict OpenSpec validation 和 diff check 全部通过。
- [x] `evidence.md` 区分 committed evidence、当前 dirty worktree、fake-only contract 和 residual external-service limit。
- [ ] 只在 staged-only candidate 中加入 change-owned paths；不混入 Event schema、generic Tool/Workflow、Redis、MCP/OpenAPI 或其他用户修改。
- [ ] 完成后将本 PRD metadata 更新为 `IMPLEMENTED`，写入实现 commit、迁移顺序、回滚演练和最终测试结果；未满足任一项时保持 `IN_PROGRESS` 或 `BLOCKED`。

## 14. OpenSpec 追踪

| PRD 需求 | OpenSpec 范围 | 当前状态 |
| --- | --- | --- |
| HAR-001 | tasks `1.1`, `2.4` | contract 与 control-plane focused evidence 已通过；broad gate 仍开放 |
| HAR-002/003/004/005/006 | tasks `3.1-3.9` | focused authority/recovery/store evidence 已通过；全量交付门禁仍开放 |
| RES-001 | tasks `4.1-4.9` | v1/v2 strict reader、legacy quarantine、accepted-only latest、异常 recovery 与 startup/lazy reconciliation 已有 focused evidence；交付门禁仍开放 |
| RES-002/003 | tasks `5.1-5.7` | hidden preparation、terminal atomic publication、Nth-member rollback、outcome read-back 和 worker capability isolation 已有 focused evidence；交付门禁仍开放 |
| SKL-001 | tasks `1.5`, `6.1-6.4` | contract focused evidence；生产 composition 未声明 |
| 发布与交付 | tasks `7.1-7.7` | `7.1-7.4/7.6` 已完成；accountable finalization 与 staged-only release 未完成 |

OpenSpec 当前 `tasks.md` 的勾选数为 `49/51`。该数字用于说明本次文档快照，不得替代提交、测试日志或生产部署证据。

## 15. 参考来源

- [`proposal.md`](../../../openspec/changes/harness-side-effect-authority-closure/proposal.md)
- [`design.md`](../../../openspec/changes/harness-side-effect-authority-closure/design.md)
- [`harness-side-effect-authority/spec.md`](../../../openspec/changes/harness-side-effect-authority-closure/specs/harness-side-effect-authority/spec.md)
- [`harness-runtime/spec.md`](../../../openspec/changes/harness-side-effect-authority-closure/specs/harness-runtime/spec.md)
- [`research-run-persistence/spec.md`](../../../openspec/changes/harness-side-effect-authority-closure/specs/research-run-persistence/spec.md)
- [`harness-skill-evolution/spec.md`](../../../openspec/changes/harness-side-effect-authority-closure/specs/harness-skill-evolution/spec.md)
- [`tasks.md`](../../../openspec/changes/harness-side-effect-authority-closure/tasks.md)
- [`evidence.md`](../../../openspec/changes/harness-side-effect-authority-closure/evidence.md)
- [`阶段 20 umbrella PRD`](20-framework-boundary-and-duplication-convergence.md)
- [`project-architecture.md`](../../architecture/project-architecture.md)
- [`business-boundaries.md`](../../architecture/business-boundaries.md)
- [`interface-layer.md`](../../architecture/interface-layer.md)
- [`persistence-boundaries.md`](../../architecture/persistence-boundaries.md)
