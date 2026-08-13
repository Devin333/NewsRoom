## 1. 基线、依赖和冻结

- [ ] 1.1 完成 `harness-workflow-graph-runtime` 的实现与严格验证，并归档使 `harness-workflow-graph` 成为 canonical capability
- [ ] 1.2 基于归档后的 canonical spec rebase 本 change，补上 `Legacy Workflow Graph Compilation` 的最终 `REMOVED` delta
- [x] 1.3 生成机器可读的生产依赖 inventory，覆盖 `framework/workflow` 92 个 tracked files、所有外部 imports、public exports、registries、reflection strings 和 CLI/API/MCP/SDK entrypoints
- [x] 1.4 盘点所有 persisted run manifests、events、checkpoints、replay bundles、artifact indexes、conversation cursors、iteration checkpoints 及其 schema/version
- [ ] 1.5 为 inventory 的每一行填写 `keep/adapt/migrate/delete/quarantine`、replacement owner、caller、数据处置、迁移 phase、验证命令和删除 commit
- [ ] 1.6 建立 architecture freeze gate，阻止新增 `framework.workflow`、`framework.harness.workflow`、`WorkflowRunner`、`WorkflowExecutor` 和 legacy schema writer
- [x] 1.7 记录当前 Research Graph golden definition、normalized graph checksum、gate evidence、terminal manifest 和 offline replay 基线
- [ ] 1.8 确认所有受管环境、artifact roots、event/checkpoint stores、index databases 和维护窗口 owner
- [x] 1.9 审计所有 active `workflow-*`、`*workflow*` OpenSpec changes；仍会同步旧 runtime requirement 的 change 必须改为 superseded/`--skip-specs` 归档或先重写为 Graph contract

## 2. Graph-only 公共契约

- [ ] 2.1 在 `framework/harness/graph` 建立最终 Graph namespace，并为 DSL、normalized graph、compiler、reader、versioning、validation、bindings 和 runtime resolution 划分 owner
- [ ] 2.2 定义不可变 `HarnessGraphDefinition`，明确 `graph_id`、`graph_version`、root Graph、activity bindings、terminal side-effect policy 和 canonical serialization
- [ ] 2.3 将 `HarnessRunSpec.workflow` 改为 `HarnessRunSpec.graph`，并同步所有内部构造、类型检查、序列化和错误码
- [ ] 2.4 将 `HarnessWorkflowGraphCompiler` 改为 `HarnessGraphCompiler`，只接受显式 Graph definition 并输出带 checksum 的 `NormalizedHarnessGraph`
- [ ] 2.5 删除 `graph=None` fallback、`entry_step_id`、`routing_rules`、`declaration_mode`、legacy schema constants 和 dual declaration reader
- [ ] 2.6 让 preflight 在 `RUN_CREATED`、checkpoint、artifact、worker 或 publication side effect 前拒绝所有 legacy Workflow declarations
- [ ] 2.7 为 Graph schema、compiler、condition、activity binding、gate、checkpoint、event 和 manifest 建立精确 version pinning 及 unknown-version fail-closed 行为
- [ ] 2.8 保留 `HarnessStepSpec` 仅用于 executable leaf lifecycle，禁止它表达 outer routing、node readiness 或 publication decision
- [ ] 2.9 更新 `framework/harness/__init__.py`、模块 `__all__` 和 type-checking imports，删除 Workflow 名称的 re-export
- [ ] 2.10 增加 Graph contract round-trip、canonical checksum、unknown construct、missing Graph、dual declaration 和 no-worker-before-preflight 测试

## 3. Harness 控制面迁移

- [ ] 3.1 将 control plane、scheduler、evaluator、state、checkpoint、durable events、compensation 和 TaskPlan 的 imports 切换到 `framework.harness.graph`
- [ ] 3.2 将 route table、condition table、activity readiness、quality gate 和 budget context 改为从 pinned Graph 读取
- [ ] 3.3 保证所有 phase transition 继续记录 durable `PLAN -> EXECUTE -> VERIFY` transcript/event，并绑定 Graph/node-instance identity
- [ ] 3.4 将 TaskPlan 限定为冻结 Graph 中显式注册 dynamic stage 的内部计划版本，不允许它修改 outer Graph 或新增未注册 worker
- [ ] 3.5 将 Sequence、Choice、Parallel-All/Any、Join、Bounded-Loop、Wait、approval、timer、signal、compensation 保持为确定性 control nodes
- [ ] 3.6 将 Function、Tool、Skill、Subagent、AgentLoop 注册为 leaf activity bindings，并让 worker 输出只进入 candidate/evidence channel
- [ ] 3.7 将 memory write、tool authorization、artifact publication 和 external side effect 都接回 Harness-owned gate/port authority
- [ ] 3.8 增加 adversarial tests，证明 worker route suggestion、LLM self-score、queue readiness 和 business service cannot alter Graph decisions
- [ ] 3.9 增加 crash recovery、checkpoint replay、gate version pinning 和 missing terminal evidence 的 Graph-only tests

## 4. Domain-neutral 能力迁出旧 runtime

- [ ] 4.1 将 manifest、artifact ref、checksum、path boundary、publication metadata 和 strict content reader 迁到 artifact-owned contracts
- [ ] 4.2 迁移 `framework/agent/artifacts/runtime/manager.py`、Research publisher 和 artifact interface caller 到 artifact owner，删除 `framework.workflow.runtime.manifest` 依赖
- [ ] 4.3 将 event projection、event migration primitives、stream identity validation 和 read models 迁到 `framework/events`
- [ ] 4.4 将 event migration/projection services 改成调用 application service/Graph event ports，禁止 interface 直接访问旧 projector/executor
- [ ] 4.5 将 cancel、signal、approval、resume、inspect、replay 和 run operation 组合到 Harness Graph application services
- [ ] 4.6 将 artifact inspection 改为读取 Graph terminal manifest，并对未迁移历史返回 typed quarantine/history diagnostic
- [ ] 4.7 将 artifact index 和 event index 改为消费 Graph run/event contracts，保持路径、checksum、sequence 和 idempotency 防护
- [ ] 4.8 迁移 `scripts/dev.py`、`interfaces/services` 和 `infrastructure/research` 的所有旧 runtime imports
- [ ] 4.9 为每个迁出职责添加 owner-level contract tests，确认新 owner 不反向导入 `framework.workflow`
- [ ] 4.10 将 attempt execution/admission 的 `DataBuffer`、Workflow Step 和 Workflow attempt contract 改为 Graph activity、node instance 和 node-output resource-owned fencing

## 5. Research Graph 化

- [ ] 5.1 将 `business/research/workflows` 迁为 `business/research/graphs`，同步 builder、module、fixture、test 和 import 名称
- [ ] 5.2 将 paper analysis composition 返回 `HarnessGraphDefinition`，移除 `HarnessWorkflowSpec` 和 legacy routing fields
- [ ] 5.3 将 static Research path 固定为 Graph `Parallel-All + VerifiedAggregation`，验证 Graph checksum 与 gate version
- [ ] 5.4 将 dynamic analysis 作为 frozen Graph 内 opt-in dynamic stage，保留 bounded `PLAN -> EXECUTE -> VERIFY` 和 durable TaskPlan
- [ ] 5.5 将 reader repair subagent declarations、memory write intent 和 promotion boundary 接到 Graph activity/gate contract
- [ ] 5.6 更新 `interfaces/composition/research.py`、Research application service 和 runtime wiring，确保 `business/research` 不导入任何旧 Workflow namespace
- [ ] 5.7 增加 Research static、dynamic、reader repair、gated failure、artifact publication、replay 和 production-adapter composition tests
- [ ] 5.8 运行 Research import boundary scan，确认旧 `paper_radar`、interface、infrastructure、generic Workflow runtime 均无直接依赖

## 6. AgentLoop 边界和运行证据

- [ ] 6.1 用 Graph activity binding 取代 `AgentLoopStepRunner`，明确 `AgentRunner` 只组装依赖，AgentLoop 只执行单 Agent loop
- [ ] 6.2 将 AgentLoop LLM request/response artifact 持久化接入 artifact owner 和 Graph node outcome；AgentLoop 不得直接发布 manifest
- [ ] 6.3 将 conversation cursor 和 iteration checkpoint 的 outer identity 改为 Graph run/node/checkpoint ref
- [ ] 6.4 将 approval request 的 waiting candidate 接回 Harness Graph Wait registration，禁止 AgentLoop 自己恢复或路由
- [ ] 6.5 更新 AgentLoop diagnostics、retry、judge、tool policy 和 structured-output tests，证明 outer gate/budget 仍由 Harness 决定
- [ ] 6.6 将 `test-agent-loop` 改为 Graph smoke fixture，检查 preflight、activity receipt、VERIFY evidence、manifest metrics 和 zero real network
- [ ] 6.7 删除 `AgentLoopStepRunner`、旧 runner registry binding、旧 Workflow smoke fixture 和仅服务它们的测试

## 7. 外部接口和 approval resume

- [ ] 7.1 设计并冻结 API major schema，将 `workflow_id/version/ref` 替换为 `graph_id/version/ref`，明确旧字段不在新 schema 中 alias
- [ ] 7.2 将 run response、status、inspection、replay、cancel、signal 和 approval resume API 迁到 Graph application service
- [ ] 7.3 将 CLI 命令和 JSON/human output 迁到 Graph identity，删除 `resume-workflow` 等旧命令并更新 help/contract tests
- [ ] 7.4 将 MCP tool、SDK method、OpenAPI schema 和 generated contract 迁到 versioned Graph resume surface
- [ ] 7.5 为 approval resume 校验 Graph run、Wait registration、checkpoint checksum、authorization、scope 和 idempotency
- [ ] 7.6 增加 interface boundary tests，证明 API/CLI/MCP/SDK 不直接构造 scheduler、executor、store 或旧 runtime
- [ ] 7.7 更新客户端调用方清单、发布说明、major cutover date 和 deprecation/deletion evidence
- [ ] 7.8 将 approval resume context 的共享 `buffer_updates` 改为 checksum-bound Graph `node_updates`，拒绝未声明 update key 和错误 node scope

## 8. 历史数据离线迁移

- [ ] 8.1 实现 migration-only schema readers，限定可读的 legacy versions、来源路径和输入 checksum
- [ ] 8.2 实现 Workflow declaration -> Graph record transformer，覆盖 manifest、events、checkpoints、replay bundles、indexes、cursor refs 和 provenance
- [ ] 8.3 为未知 schema、缺失 Graph identity、缺失 gate evidence、非法路径、checksum mismatch、sequence gap 和 ambiguous record 定义稳定 quarantine reason codes
- [ ] 8.4 实现 dry-run inventory、deterministic migration-plan checksum、idempotent rerun 和 conflict detection
- [ ] 8.5 用 fixture snapshot 验证转换前后 identity、sequence、artifact containment、terminal status、gate evidence 和 replay decision 等价性
- [ ] 8.6 确认 migrator 在测试中 live LLM/Tool/worker/retrieval/memory/publication call count 始终为零
- [ ] 8.7 对每个受管环境执行 backup、read-only freeze、in-flight run drain 和 writer stop 检查
- [ ] 8.8 将可转换记录写入 staging Graph stores/indexes，执行 cross-store referential integrity、checksum、count conservation 和 read-back 校验
- [ ] 8.9 原子切换 Graph store/index pointer，保留源 snapshot 只读，生成 completion report 和 quarantine report
- [ ] 8.10 演练切换失败、pointer rollback、staging corruption、重复迁移和恢复到 Graph-aware release 的路径
- [ ] 8.11 所有环境验收后删除 active migrator/legacy reader，仅保留签名报告和必要历史 fixture

## 9. 删除旧 Workflow runtime

- [ ] 9.1 运行 caller-count gate，确认 `framework/workflow`、`framework/specs.workflow`、Harness Workflow namespace 和旧 runner symbols 的 production caller 全部为零
- [ ] 9.2 删除 `framework/workflow/runners` 及其 registry、executor-facing tests，确保 leaf activity tests 已迁到 Graph binding tests
- [ ] 9.3 删除 `framework/workflow/routing`、`scheduling`、`compiler` 和 `governance`，确保 Graph evaluator/scheduler/budget tests 已覆盖原行为
- [ ] 9.4 删除 `framework/workflow/checkpoint`、`buffer`、`inspection`、`operations` 和 `runtime`，确保 Graph checkpoint/event/artifact/application services 已接管
- [ ] 9.5 删除 `framework/workflow/specs`、`framework/specs/workflow.py`、Workflow registry 和仅服务旧 aggregate 的 exports
- [ ] 9.6 删除 `framework/harness/workflow` legacy namespace、`HarnessWorkflowSpec`、legacy reader/compiler、routing models 和 schema constants
- [ ] 9.7 删除 `framework/__init__.py` 和其他 root package 的 `WorkflowRunner`、`WorkflowExecutor`、legacy `RunResult` 等 exports
- [ ] 9.8 删除旧 Workflow API/CLI/MCP/SDK surface、schema writers/readers、reflection registrations 和 compatibility tests
- [ ] 9.9 删除 only-legacy fixtures；保留并标记离线 migration fixture，不允许被 production import
- [ ] 9.10 对删除后的 tracked files、imports、public symbols、registries 和 generated schemas 生成 deletion proof

## 10. Canonical OpenSpec 和文档同步

- [ ] 10.1 将本 change 的 Graph-only delta 同步到 `harness-graph` canonical spec，并移除 `Legacy Workflow Graph Compilation`
- [ ] 10.2 新增并同步 `graph-storage-indexing`、`approval-graph-resume-interfaces` 等 Graph capability，退役旧 capability requirements
- [ ] 10.3 更新 `harness-runtime`、`research-runtime`、AgentLoop、artifact、architecture、interface 和 cleanup specs，消除要求旧 runtime 的条款
- [ ] 10.4 归档 `workflow-runtime-target-closure`、`workflow-storage-indexing` 和已 superseded approval workflow capability，保留历史 provenance
- [ ] 10.5 更新架构文档、运行手册、CLI/API/MCP 文档和 Research composition 文档，统一表述为 Graph outer orchestration + AgentLoop inner loop
- [ ] 10.6 对 active source/docs/specs 执行 stale reference audit，所有剩余 Workflow 名称必须命中具体历史 allowlist
- [ ] 10.7 运行 `openspec validate graph-only-orchestration --strict` 和 `openspec validate --all --strict`
- [ ] 10.8 核对每个旧 Workflow capability 的全部 requirements 已迁入 Graph owner 或显式删除，不能只删除 capability 中的一部分 requirement

## 11. 验收和发布门禁

- [ ] 11.1 运行 `python -m scripts.dev compile`，修复所有 Graph namespace、import 和 schema 错误
- [ ] 11.2 运行与变更范围匹配的 Graph/Harness/Research/AgentLoop/artifact/approval/storage focused tests
- [ ] 11.3 运行 `python -m scripts.dev test` 和 `python -m scripts.dev smoke`
- [ ] 11.4 执行 production import/export scan，确认旧 runtime symbol/import 为零
- [ ] 11.5 执行 Graph static/dynamic Research end-to-end、approval wait/resume、crash recovery、offline replay 和 artifact inspection 验收
- [ ] 11.6 检查 replay 的 live call count、publication count、memory-write count 和 tool authorization count 均符合 zero-side-effect 规则
- [ ] 11.7 检查 migration count conservation、checksum、quarantine、pointer switch、rollback evidence 和环境 completion reports
- [ ] 11.8 执行 release review，确认没有 compatibility facade、fallback executor、legacy writer、hidden feature flag 或未登记历史 store
- [ ] 11.9 在所有检查通过后再提交实现 commit；本规划阶段不执行上述代码/数据变更
