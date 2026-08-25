## Why

仓库当前同时存在两套外层编排模型：Harness Graph runtime，以及更早的线性 Workflow runtime（`steps`、routing rules、runners、checkpoint 和 compatibility exports）。Research 主路径已经用显式 Graph 声明并由 `HarnessControlPlane` 执行，但运行契约仍叫 `HarnessWorkflowSpec`，编译器仍允许 `graph=None` 的 legacy 声明；与此同时，artifact、event、inspection、operation、storage 和 CLI 仍有生产代码直接依赖 `framework.workflow`。

这种“双权威”状态会持续制造错误边界：调用方无法判断应该接入 Workflow、Graph 还是 `AgentLoop`，旧兼容层也允许新代码重新引入 Workflow-shaped orchestration。项目需要一次有明确数据迁移和删除门槛的 breaking cutover：Graph 成为唯一外层编排模型；`AgentLoop` 只保留为 Graph executable node 可调用的有界单 Agent worker loop。

## What Changes

- 采用一次性、单向 Graph-only cutover：当前 owner 授权仓库内直接替换 production run contract、writer/reader、runtime route、public contract 和 persisted authority，并在 replacement coverage 到位后删除 legacy runtime。前置 change 归档、受管环境 owner、rollback point、rollback drill 和 observation window 不再是实现或删除门槛。
- **BREAKING**：每个 Harness run 必须携带显式、版本化且预检通过的 Graph definition；在 worker 执行前拒绝 `graph=None`、legacy `routing_rules`、legacy entry-step 声明和任何双模式声明。
- **BREAKING**：将 `HarnessRunSpec.workflow`、`HarnessWorkflowSpec`、`HarnessWorkflowGraphCompiler` 及其公开/persisted Workflow identity 改为 Graph 命名和 Graph-only contract；删除 legacy compiler、legacy reader 和 active fallback。
- **BREAKING**：在删除 `framework/workflow` 前，先把 artifact manifest/integrity、event projection/migration、run operations、inspection/replay 和 storage indexing 迁到 Graph-owned 或 domain-neutral owner；不建立新的 Workflow compatibility facade。
- 保留并复用已由 `graph-artifact-cost-retention` 落地的 `framework/harness/artifacts` catalog、quota、usage ledger、GC、cost reporting、alerts 和 governance runtime；本变更只迁移其仍依赖 legacy Workflow manifest/manager/publisher 的桥接边界，不重写或删除这些 Graph-native 能力。
- **BREAKING**：将 approval pause/resume、checkpoint/recovery、signal 和 run operation 迁到 Harness Graph wait/control-plane application services；interface 层只调用 application service，不直接访问 executor 或 store。
- **BREAKING**：live runtime 不迁移、不兼容也不恢复 Workflow run manifests、events、checkpoints、replay bundles 和 indexes。legacy record 只能被隔离的历史工具识别并返回稳定 quarantine reason；Graph reader、resume、replay execution 和 publication 必须直接拒绝。
- **BREAKING**：删除通用 `framework/workflow` 的 runner、executor、scheduler、routing、checkpoint、inspection、operation、buffer、compiler、governance 和 spec 模块，并删除 `framework` root 的 `WorkflowRunner`、`RunResult` 等兼容导出。
- 把 `framework/harness/workflow` 中真正属于 Graph 的 DSL、normalized graph、compiler、validation、binding authority 和 runtime resolution 收敛到 `framework/harness/graph`，使包名和公开类型表达实际模型。
- 把 Function、Tool、Skill、Subagent、AgentLoop 等执行能力注册为 Graph activity/worker bindings；Sequence、Choice、Parallel、Bounded Loop、Wait、Join、Gate 和 Compensation 始终由 Harness 确定性控制，不能伪装成 worker runner。
- **BREAKING**：control-plane run result、gate、Wait/resume、side-effect 和 inspection 不再把 `HarnessGraphState` 投影回 flat `HarnessState`；删除 `LEGACY_UNBOUND`、synthetic legacy identity 与无 caller 的 flat checkpoint/replay runtime。
- **BREAKING**：SubAgent production invocation/transcript/receipt/bundle 固定为 Graph-only major schema；v1/v2 reader 不再属于 live runtime，旧 schema 只允许在隔离 history-only tooling 中识别，随后删除 active reader/export。
- **BREAKING**：`BusinessContext`、`TraceContext`、propagation carrier、tool metrics、Event catalog/read model 统一切到 Graph identity；删除 Workflow current schema registration、旧 Event facade 和 production-importable migration service。
- **BREAKING**：Memory、Governance、Worker task/result、Skill context、LLM structured-output policy 和 observability metadata 统一使用 Graph run/node/stage scope，删除 Workflow scope/identity aliases。
- **BREAKING**：Harness RAG session、ContextEnvelope、snapshot/cache/materializer 和 Research RAG caller 统一绑定 exact Graph identity；保留独立 RAG session 能力，但删除 nullable Workflow/session identity fallback。
- 删除 `WorkflowArtifactRef`、`WorkflowArtifactPublisher`、`LocalArtifactPublisher` 等 legacy bridge，但保留 `ArtifactManager` raw storage/integrity/path-safety primitives 与 `framework/harness/artifacts` 的完整 Artifact authority。
- 将 Research 的 `workflows/`、`*_workflow.py` 和 builder 命名迁到 Graph；静态 `Parallel-All + VerifiedAggregation` 与 opt-in dynamic TaskPlan 都必须依附冻结的外层 Graph。
- 保留 `AgentLoop` 的单 Agent LLM/tool/judge 循环，但禁止它决定外层 Graph routing、quality pass/fail、budgets、memory writes、tool authorization、approval state 或 publication。
- 增加 import boundary、public-symbol、schema、history quarantine、replay、approval resume、Research end-to-end 和 repository scan gates，证明旧 Workflow runtime 不再是生产依赖或执行权威。

## Capabilities

### New Capabilities

- `graph-only-orchestration`：定义 Graph-only declaration、execution、persistence、inspection、replay、历史迁移和旧 Workflow runtime 退役规则。
- `harness-graph`：接管 `harness-workflow-graph` 的 Graph DSL、compiler、validation 和 deterministic identity 要求，但不包含 legacy Workflow compilation。
- `graph-storage-indexing`：定义 Graph run artifacts 和 Graph events 的 storage indexing contract。
- `approval-graph-resume-interfaces`：定义 Graph approval resume 的 API、CLI、MCP 和 SDK surface。

### Modified Capabilities

- `harness-workflow-graph`：将所有非 legacy Graph 要求直接迁入 `harness-graph`，删除 `Legacy Workflow Graph Compilation` 并退役旧 capability；不等待前置 change 归档，也不保留 legacy compiler/reader。
- `harness-runtime`：把外层控制权、route source、gate binding 和 context contract 从 Workflow 改成显式 Graph definition。
- `research-runtime`：让 Research Graph definitions 成为唯一编排契约，移除 Research workflow declarations。
- `agent-loop-runtime`：把 approval decision 从 `WorkflowRunner` resume 迁到 Harness Graph typed Wait cause，并由 control plane 在 durable commit 后自动推进。
- `agent-loop-target-closure`：从 Graph executable node 调用 AgentLoop，并由 Harness Graph 保持 routing authority。
- `agent-loop-p0-output-contract-artifacts`：由 Graph activity lifecycle 和 artifact owner 持久化 AgentLoop LLM artifacts，不再依赖 `WorkflowExecutor`。
- `agent-loop-cursor-runtime-wiring`：传递 Graph run/node/checkpoint context，不再传 Workflow step context。
- `agent-loop-conversation-cursor`：将 cursor 的 workflow checkpoint identity 改为 Graph checkpoint identity。
- `agent-loop-iteration-checkpoint`：将 iteration checkpoint 的 workflow checkpoint identity 改为 Graph checkpoint identity。
- `approval-resume-context-interfaces`：将旧 mutation-shaped resume context 收敛为只读 Graph Wait/approval context，不再暴露 `buffer_updates`、`node_updates` 或 routing metadata。
- `approval-workflow-resume-interfaces`：将要求迁入 `approval-graph-resume-interfaces` 后退役旧 capability。
- `artifact-runtime-boundary`：将 legacy `WorkflowArtifactRef` path-boundary 要求迁到 Graph artifact reference contract。
- `artifact-inspection-interface`：通过 Graph run manifest 和 artifact-owned contracts 提供 inspection，移除旧 Workflow inspector 依赖。
- `workflow-storage-indexing`：将要求迁入 `graph-storage-indexing` 后退役旧 capability。
- `test-agent-loop-runner`：把 `test-agent-loop` 从 Workflow smoke 改为 Graph activity smoke。
- `interfaces-contracts`：让同步 run status 和 entrypoint dependency 明确面向 Graph/application service，而非 Workflow runtime。
- `architecture-boundary-governance`：从“spec 不导入 Workflow runtime”升级为生产代码和公开导出均不得依赖已退役 runtime。
- `attempt-execution-integrity`：将 `DataBuffer`/Workflow-attempt fencing 迁为 Graph node-output resource ownership，同时保留 fail-closed determinacy。
- `attempt-deadline-admission`：将跨层 admission scope 从 Workflow Step 改为 Graph activity/node instance，并移除 `DataBuffer` 前提。
- `structure-cleanup-governance`：移除 `framework.workflow.specs` compatibility facade 和 root Workflow exports。
- `workflow-runtime-target-closure`：删除要求保留 Workflow models、constructors 和 import compatibility 的全部要求，退役该 capability。
- `legacy-runtime-cleanup`：把“保留有用 Workflow utilities/correlation”的宽泛条款收敛为迁移有用能力后删除旧 runtime，避免该规范重新授权 compatibility layer。

## Impact

- 受影响 runtime：`framework/harness/workflow`、`framework/harness/control_plane`、`framework/harness/subagents`、`framework/harness/runtime`、`framework/workflow`、`framework/specs`、`framework/agent/artifacts`、`framework/events`、`framework/memory`、`framework/governance`、`framework/workers`、`framework/skills`、`framework/llm`、`framework/tool_runtime`。
- 受影响生产调用方：`business/research`、`interfaces/services`、`interfaces/composition`、`infrastructure/research`、`scripts/dev.py` 以及所有 run operation/inspection/replay/approval entrypoints。
- 受影响持久化契约：run manifests、event projections、Graph/workflow checkpoints、replay bundles、artifact index records、conversation cursor/iteration checkpoint 和携带 Workflow identity 的 API/CLI/MCP/SDK payload。
- 受影响测试与架构规则：旧 Workflow runtime contract tests、import boundary tests、Research composition tests、approval resume tests、artifact/replay/storage tests，以及要求保留兼容导入的 canonical OpenSpec requirements。
- 当前实时代码盘点显示 `framework/workflow` 有 92 个 tracked files，且 10 个外部生产模块仍直接导入旧 package；第 10 个调用方是已归档 Artifact governance change 新增的 `infrastructure/research/graph_artifact_lifecycle.py`。apply 阶段必须持续刷新机器可读 inventory，不能把这些数字当作永久基线。
- 本 proposal 授权直接激活 Graph-only repository production path，并删除对应 legacy writer、reader、fallback 和 runtime。实现仍按可验证的职责边界分 commit，但不得以 feature flag、dual writer/reader 或 compatibility facade 保留回退路径。
- event projection、storage indexing 与 node-output fencing 必须由 Graph owner 接管并通过 replacement tests；旧 reader、旧 pointer adapter 和 `DataBuffer` 在调用方清零后直接删除，不要求 rollback evidence。
