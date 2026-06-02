# 业务层边界

本文说明 NewsRoom `business/` 层的当前职责边界，并补充
`docs/architecture/framework-boundaries.md`：`framework/` 只承载领域无关运行时能力，
不得导入 `business`、`interfaces` 或具体 `infrastructure` 实现。

## 分层职责

- `business/foundation/`：业务基础模型、枚举、注册表、策略快照、反馈学习模型和业务 skill 内容包。它不能导入 `business.layers` 或 `business.boards`。
- `business/layers/`：可复用的业务处理流水线，包括 signal、extraction、relation、analysis、output、memory。它可以依赖 foundation，但不能依赖 boards。
- `business/boards/domain/`：board 通用领域服务，承载 selection、ranking、quality、evidence assembly、artifact/evidence/memory refs 等可复用业务规则。
- `business/boards/application/`：board 应用门面与装配，承载 `BoardServiceRuntime`、feedback service、improvement service 等用例协调能力。
- `business/boards/services/`：历史兼容导出层。新代码应优先从 `business.boards.domain` 或 `business.boards.application` 导入。
- `business/boards/productized/`：productized board workflow 的应用用例、step adapter、workflow spec、专用中间模型和 workflow 输出服务。
- `business/boards/<board_type>/`：单个 board 的策略、presenter、ranking rules、runner 和 workflow 入口。它只承载 board 特化行为。

## Workflow Step 边界

Productized workflow step 只做三件事：

1. 从 workflow buffer 读取声明过的 key。
2. 调用 `ProductizedBoardUseCases` 的对应方法。
3. 返回声明过的输出 key。

Step 不直接执行 signal selection、ranking、evidence、quality、feedback、improvement、subscription 或 output bundle 构建逻辑。
workflow IO 声明集中在 `business/boards/productized/workflow.py`；
step adapter 集中在 `business/boards/productized/steps.py`；
`business/boards/_productized_steps.py` 只保留旧导入路径兼容。

## Workflow Buffer Collection 规则

workflow step 从 buffer 读取 list/tuple 类型集合时，应把读取值视为借用值，不能原地修改。

- 事件列表追加必须通过 `workflow_buffer_access.read_buffer_list()` 或 `append_buffer_items()` 先复制再追加。
- step 返回新的集合值，由 workflow runner 写回声明过的 output key。
- `buffer.read()` 结果不得直接 `.append()`、`.extend()` 或嵌套原地修改。
- 当某个 key 需要跨 step 承载复杂中间状态时，应优先新增正式模型或命名清晰的 buffer key，不要塞进 `metadata`。

当前 daily intelligence workflow 的 `source_events` 和 `quality_events` 已使用该 helper 收敛 read-copy-write 约定。

## Workflow Buffer Key 命名空间

daily intelligence workflow 进入兼容迁移期：业务函数继续写旧 key，同时通过 `buffer_key_aliases.with_namespaced_aliases()` 双写命名空间 key。

- source 相关输出使用 `sources.*`，例如 `sources.errors`、`sources.events`、`sources.ranked_items`。
- evidence 相关输出使用 `evidence.*`，例如 `evidence.bundle`、`evidence.verified_findings`。
- quality 相关输出使用 `quality.*`，例如 `quality.events`、`quality.result`。
- report 相关输出使用 `report.*`，例如 `report.draft`、`report.final`。
- agent feedback 输出使用 `agent.feedback.*`。

旧 key 仍是现有公开兼容面；新代码应优先声明并消费命名空间 key。后续迁移完成前，禁止在单个 step 中临时发明未登记的 dotted key。

## Agent Feedback 边界

Agent 间反馈不应隐藏在各 agent output 的自由形态字段里，也不应由 `finalize_report` 反向猜测。

- verifier/editor 对 writer、human review 或 publication gate 的反馈先归一化为 `agent_feedback_events`。
- 聚合指标写入 `agent_feedback_summary`，供 final report、blocked report、quality result 和 artifact manifest 使用。
- 当前闭环雏形只负责“显式化反馈信号”，不在 workflow step 内直接重跑 agent 或重新收集 source。
- 后续如需触发 writer 局部重写、planner 调整或 source recollect，应由应用层 routing / policy service 消费这些正式反馈模型。

## BoardServiceBase 边界

`BoardServiceBase` 是 board 门面，只保留：

- context 解析和公开调用入口；
- board-specific policy hook；
- 旧调用方兼容方法；
- 对 `BoardServiceRuntime` 装配结果的兼容属性暴露。

通用服务装配已移动到 `business/boards/application/service_runtime.py`。
selection、quality、references 等领域规则位于 `business/boards/domain/`。
`business/boards/services/` 中同名模块只作为兼容导出，不再是新逻辑落点。

## Productized 用例边界

`ProductizedBoardUseCases` 是工作流应用入口，负责协调专用服务，不承载具体业务算法。

- `ProductizedEvidenceService` 委托 `BoardEvidenceAssemblyService` 生成 evidence refs/items，并把正式中间结果写入 `ProductizedRunState`。
- `ProductizedRankingService` 委托 `BoardSignalRankingService` 排序 signals，并返回正式 `ranked_signals` step 输出。
- `ProductizedBoardOutputBundleBuilder` 负责 artifact-facing metadata 合并，并生成 `ProductizedBoardOutputBundle`。
- `ProductizedImprovementWorkflowService` 负责 recommendation、proposal、policy experiment application、measurement 和 report 输出。

跨 step 的运行态中间结果使用 `ProductizedRunState`。`metadata` 只保留对外 artifact 和历史兼容字段。

## Metadata 使用规则

`metadata` 只能承载对外输出需要的摘要、序列化快照或兼容字段。跨 step 的运行时中间结果必须使用正式 buffer key 或模型。

本轮新增的正式字段：

- `BoardRunResult.board_output`：显式承载 board output payload。
- `BoardRunResult.pipeline_snapshot`：显式承载 pipeline snapshot，类型为 `BoardRunPipelineSnapshot`。
- `BoardRunResult.report_payloads`：显式承载从 board output 提取的 report payload。
- `BoardRunResult.metadata["board_output"]`：仅作为历史兼容字段保留。
- `ProductizedRunState`：承载 skill traces、extracted entities、evidence refs/items、deduplication result、trend analysis 和 improvement context。

新代码应优先读取正式字段，例如 `BoardRunResult.board_output` 和 `productized_run`，不要从 `metadata` 反向推断内部状态。
`BoardRunApplicationResult` 是 board run 组装阶段的正式 application result model；
`BoardRunMetadataBuilder` 只负责把它投影成旧调用方需要的 metadata 兼容字段。

## Improvement 边界

improvement 主流程是：

`feedback -> learning signal -> recommendation -> policy experiment profile -> applied policy experiment -> measurement`

`ImprovementProposalBuilder` 将 recommendation 转换为 `policy_experiment` proposal 和 `PolicyExperimentProfile`。
`ImprovementApplier` 返回 `PolicyExperimentApplicationContext`，主字段为：

- `applied_policy_experiments`
- `skipped_policy_experiments`
- `proposal_ids`
- `measurement_plan`

`applied_overrides` 和 `skipped_overrides` 只作为历史兼容属性保留，内容等同于 policy experiment 结果。
旧 `proposed_patch` 字段只用于读取历史持久化数据；新 proposal 不再生成 patch payload。

## 禁止依赖

- `framework/` 不得导入 `business`、`interfaces` 或具体 `infrastructure`。
- `business/foundation/` 不得导入 `business.layers` 或 `business.boards`。
- `business/layers/` 不得导入 `business.boards`。
- `business/boards/` 不得导入具体存储 adapter。
- workflow step 模块不得直接导入 lower-layer pipeline、subscription/improvement/output 构造器来承载业务逻辑。
