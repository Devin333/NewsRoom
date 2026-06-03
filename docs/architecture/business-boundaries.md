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

## Board Workflow Execution 边界

`business/boards/_workflow.py` 负责编排 board 业务阶段：context 解析、signal selection、pipeline、board result、policy、quality feedback 和最终结果组装。

stage 执行、stage outcome 记录、失败 stage 的 finish/publish 语义由 `business/boards/_workflow_execution.py` 承载。业务 workflow 不在异常路径继续构建 board result；失败会记录到 `BoardWorkflowExecution` 后立即重新抛出，调用方可从 `last_execution` 或 metadata 中读取执行证据。

## Daily Runtime Assembly 边界

daily intelligence 的普通 Runner 和 agentic Runner 都以 `DailyIntelligenceRuntime` 作为主装配模型。`source_runtime_assembly_from_runtime()` 只负责从 runtime 投影 connector/source collector 兼容视图，不再由各 Runner 手工拼装 connector。

新增 Runner 入口时，应优先接收或构建 `DailyIntelligenceRuntime`，再按需投影 workflow-specific adapter；不要重新引入动态属性绑定或并行的初始化路径。

## Daily Workflow Timeout 边界

daily intelligence 的全局运行时预算声明在业务 workflow spec 中，通过 `daily_workflow_runtime_policy()` 生成 `WorkflowPolicySpec`，由 `framework.workflow.runtime` 统一执行。

- workflow-level timeout 是整条 workflow 的兜底预算，用来防止 source collection、agent loop、report finalization 或 quality gate 的组合运行无限延长。
- connector、tool、LLM client 的 timeout 仍是各自外部调用的局部保护，不能替代 workflow-level timeout。
- 新增 daily workflow profile 时，应复用或显式扩展该 runtime policy，不要把全局超时写入 `metadata` 或散落在 runner 装配逻辑里。

## Source Config 边界

`business.layers.signal.source_config` 负责 `configs/sources.yaml` 的 schema 和安全校验：顶层只允许 `fetch`、`sources` 和已登记的 PRD source sections；显式 `sources` 条目只允许正式 `SourceDefinition` 字段；connector-specific 字段必须放入 `metadata` 或使用对应 PRD section。

fetch policy 的 `allowed_domains` 是 live source URL 的边界。加载 source registry 时必须校验所有 fetchable source URL 落在 allowlist 内，并拒绝 `fixture://`、URL 凭证、secret-like metadata 和拼写错误配置字段。

配置文件读取和 JSON/TOML/YAML 解析错误统一归一为 `SourceConfigError`，错误消息只暴露格式、位置和路径，不回显配置文件内容。接口层诊断只消费该错误并报告 `source_config` readiness，不复制 source schema 或 allowlist 规则。

daily intelligence runtime 直接从 `business.layers.signal.source_config` 加载默认 source registry 和 fetch policy；`daily_intelligence/source_config.py` 只保留 `ensure_live_source_registry()` 这类 workflow-local live gate，不再作为默认配置 loader 的 legacy adapter。

daily source connector 的运行参数由 `SourceConnectorRuntimeOptions` 统一投影：`query`、`manual_records`、`repository`、`github_mode`、`github_discussion_category`、`story_list`、`subreddit`、`listing`、`time_range`、`tag` 和 `site` 等 dispatcher 消费的 connector-specific 字段只允许在该边界从 `SourceDefinition.metadata` / request topic 读取。`DailySourceCollector` 和 `DailySourceRecollectionExecutor` 创建该 options view 后传给 fetch request 构造与 `SourceDispatcher`；dispatcher 的 `_fetch_*` handler 只消费正式 options 字段，不再散落读取 legacy metadata key。Manual curated records 通过 `ManualSourceRecords` / `manual_records` 显式传给 connector；arXiv search query 通过 `query` 显式传给 connector；GitHub repository/query/collection mode/discussion category 通过 `repository`、`query`、`github_mode` 和 `github_discussion_category` 显式传给 connector；Hacker News story list 通过 `story_list` 显式传给 connector；Reddit subreddit/listing/time range 通过 `subreddit` / `listing` / `time_range` 显式传给 connector；community source 的 tag/site 通过 `tag` / `site` 显式传给 connector；外部 connector 对这些 metadata key 的读取只保留为历史调用兜底。

GitHub GraphQL token env 属于 connector-level 鉴权选项，由 infrastructure 层 `GithubConnectorRuntimeOptions` 承载；显式参数优先，`SourceDefinition.metadata["token_env"]` 只作为历史 source 配置兜底。daily business dispatcher 不应理解 token env 这类鉴权细节。

source connector dispatch 观测使用 `SourceFetchRequest.connector_name` 作为正式字段；`metadata["connector_name"]` 只作为 artifact/legacy 兼容投影保留。`build_source_connector_dispatch_report()` 必须优先消费正式字段，只有读取历史 payload 时才回退到 metadata。

## Source Processing 边界

`business.layers.signal.source_processing` 承载 source 归一化、去重、质量评分、排序、freshness、traceability 和 governance 报告构建。daily workflow step 只负责 buffer read/write、错误兜底和调用这些 layer service，不直接重新实现评分、追踪或报告规则。

source 处理链路的正式中间模型是：

- `NormalizedSourceItem.lineage`：承载 raw -> normalized 的来源链路。
- `NormalizedSourceItem.ranking_signals` / `SourceRankingSignals`：承载 authority、duplicate cluster、historical importance 和 subscription tag 等 ranking 输入信号。
- `RankedSourceItem.lineage`：承载 normalized -> ranked 的来源链路。
- `RankedSourceItem.ranking_trace` / `SourceRankingTrace`：承载 ranking 组件分数、最终分数和 fallback 标记。
- `RankedSourceItem.source_quality` / `SourceItemQualityScore`：承载 source quality 评分结果。

`metadata["lineage"]`、`metadata["source_quality"]`、`metadata["source_authority_score"]` 和 `metadata["duplicate_cluster"]` 只作为 artifact-facing / legacy 输出投影保留。质量评分、ranking report 和 traceability report 必须消费正式字段；旧 payload 可以在模型构造时被投影成正式字段，但业务逻辑不得通过修改 metadata 来影响 ranking、traceability 或 quality 判断。

`business.layers.signal.records` 是历史导入路径兼容 facade，只允许 re-export foundation source models 和 canonical `source_processing` service；不得重新实现 normalize、deduplicate、rank 或 quality 算法。`business.layers.signal.pipeline` 消费该 facade，不直接复制 source ranking 规则。

`business.layers.signal.signal_projection.SourceSignalProjectionService` 负责把 `RawSourceItem` 投影为业务 `Signal`，包括 `SourceRef`、canonical URL、metrics、tags 和 raw confidence。`SignalPipeline` 只编排 raw -> normalized -> deduplicated -> ranked -> signal 的流程，并传入处理阶段与追加 metrics；不得在 pipeline 主体里重新拼装 source projection 字段。normalized/ranked 阶段必须通过 `SourceSignalProjectionInput.source_reliability` 和 `ranking_signals` 显式传递质量输入，metadata 只允许作为 raw/legacy 输入兜底。

source fetch error 的运行期策略由 `SourceErrorRuntimeMetadata` 投影，`DailySourceCollector` 和 `DailySourceRecollectionExecutor` 只消费 `retryable`、`source_health_affecting` 和 `phase` 的正式 view；旧 `SourceError.metadata` 只作为兼容输入。

source artifact 发布侧同样不得对 `source_errors` 做 duck typing。`SourceArtifactWriter` 的公开入口可以接收历史 dict payload，但必须先通过 `SourceErrorArtifactInput` 归一化为正式 error artifact 输入；legacy dict 到 `SourceError` 的转换、artifact id 生成、历史 `metadata["request_id"]` 读取和 request/response ref 投影都停留在 input view。error writer 只消费 `source_id`、`error_id`、`request_id`、`request_ref`、`response_ref` 和正式 `SourceError` payload，不再通过 `dict.get("error_type")`、`getattr()` 或直接读取 metadata 猜测错误结构。

source fetch request/result artifact 输入由 `business.layers.signal.source_artifact_inputs.SourceFetchRequestArtifactInput` / `SourceFetchResultArtifactInput` 投影。`SourceArtifactWriter` 可以接收历史 mapping payload，但 fetch request/result artifact id、response headers artifact、status/content-type 和 response URL 只能消费这些 input view 的正式字段；request id fallback、source id fallback 和 response headers 从 metadata 的兼容读取必须停留在 input view 中，writer 主体不得继续保留 `_string_value()`、`_metadata_value()` 或 `_optional_value()` 这类通用 duck-typing helper。

source item artifact 输入由同一模块的 `SourceItemArtifactInput` 投影。raw item 的 `source_id`、`source_item_id`、raw content、raw/parse artifact ref 和 legacy mapping fallback 都属于 input view 的职责；`SourceArtifactWriter` 只消费该 view 的正式字段来写 raw content、source item 和 parsed-items index，不再在发布编排主体里通过 `_raw_content()` / `_existing_artifact_ref()` 或 `dict.get("source_item_id")` 猜测 raw item 结构。

source item、raw content 和 parsed-items index 的具体写入职责由 `_SourceItemArtifactWriter` 承载；fetch request/result、response headers 和 request/result artifact ref 索引由 `_SourceFetchArtifactWriter` 承载；source error artifact、request/response ref 关联和 redacted error payload 构建由 `_SourceErrorArtifactWriter` 承载；source artifact index 的计数和写入由 `_SourceArtifactIndexWriter` 承载；`SourceArtifactWriter` 只负责编排 item/fetch/error/index 写入结果。新增 source artifact 类型时，应优先新增对应 input view 或小型 writer，不要把 payload 解析、ref 索引、index 汇总和文件写入细节继续堆回 `SourceArtifactWriter.write_source_artifacts()`。

## Workflow Buffer Collection 规则

workflow step 从 buffer 读取 list/tuple 类型集合时，应把读取值视为借用值，不能原地修改。

- 事件列表追加必须通过 `workflow_buffer_access.read_buffer_list()` 或 `append_buffer_items()` 先复制再追加。
- step 返回新的集合值，由 workflow runner 写回声明过的 output key。
- `buffer.read()` 结果不得直接 `.append()`、`.extend()` 或嵌套原地修改。
- 当某个 key 需要跨 step 承载复杂中间状态时，应优先新增正式模型或命名清晰的 buffer key，不要塞进 `metadata`。

当前 daily intelligence workflow 的 `source_events` 和 `quality_events` 已使用该 helper 收敛 read-copy-write 约定。

## Workflow Buffer Key 命名空间

daily intelligence workflow 进入兼容迁移期：业务函数继续写旧 key，同时通过 `buffer_key_aliases.with_namespaced_aliases()` 双写命名空间 key。

- source 相关输出使用 `sources.*`，例如 `sources.errors`、`sources.events`、`sources.ranked_items`；补源闭环使用 `sources.recollection_profile`、`sources.recollection_execution_plan`、`sources.recollection_execution_report` 和 `sources.recollection_quality_assessment`。
- evidence 相关输出使用 `evidence.*`，例如 `evidence.bundle`、`evidence.verified_findings`。
- quality 相关输出使用 `quality.*`，例如 `quality.events`、`quality.result`、`quality.human_review_resume_route`。
- report 相关输出使用 `report.*`，例如 `report.draft`、`report.final`。
- agent feedback 输出使用 `agent.feedback.*`。

旧 key 仍是现有公开兼容面；新代码应优先声明并消费命名空间 key。后续迁移完成前，禁止在单个 step 中临时发明未登记的 dotted key。

`finalize_report` 已进入命名空间优先读取阶段：workflow spec 通过 `with_namespaced_primary_read_keys()` 先声明 `report.*`、`quality.*`、`evidence.*`、`agent.feedback.*` 和 `sources.recollection_quality_assessment`，再保留旧 key 作为兼容入口；workflow adapter 仍通过统一 buffer access helper 读取，不直接关心 legacy / namespaced 分支。人工审核恢复也通过正式 `human_review_resume_route` / `quality.human_review_resume_route` 传递，finalization usecase 只消费该 route，不从 approval metadata 反推发布、阻断或重写决策。

source/evidence 主链路也已进入命名空间优先读取阶段：`require_sources`、`normalize_sources`、`deduplicate_sources`、`rank_sources` 和 `build_evidence` 的 workflow spec 先声明 `sources.*` / `evidence.*` 输入，再保留旧 key 作为兼容入口。对应业务函数仍通过 `workflow_buffer_access.read_buffer_value()` 读取 canonical 业务 key，由 helper 负责 namespaced-first fallback；step 不应自行写 legacy / namespaced 分支判断。

函数型 feedback/recollect step 同样使用命名空间优先读取：`collect_agent_feedback` 优先声明 `quality.*` 和 `agent.feedback.*` 输入，`recollect_sources` 优先声明 `sources.recollection_execution_plan` 及已有 `sources.*` 快照输入。

Agent loop step 也使用命名空间优先读取，但 agent 本身仍消费 canonical 业务输入。`DailyAgentInputCanonicalizingRunner` 在 business 层把 `sources.*`、`evidence.*`、`quality.*`、`report.*`、`agent.feedback.*` 和 `agent.<label>.*` 输入投影回 agent spec 期待的 canonical key，并让命名空间值覆盖 legacy 值；framework `AgentLoopStepRunner` 只负责按 spec 读取 buffer 和调用 runner，不承载 daily 专属 alias 解析。daily agent output normalizer 负责把旧业务输出 key 投影成命名空间 alias，agentic workflow spec 必须在对应 agent step 的 `write_keys` 中声明这些 alias。planner/analyst 的业务 payload 使用 `agent.planner.research_plan` 和 `agent.analyst.analysis_result` 作为正式中间结果 key，notes 使用 `agent.<label>.notes`；旧 `research_plan`、`analysis_result` 和 `*_notes` 只保留为兼容入口。agent loop telemetry 使用 `agent.<label>.loop.*`，例如 `agent.planner.loop.result`、`agent.writer.loop.metrics` 和 `agent.editor.loop.llm_call_artifacts`；映射由 business 层 `buffer_key_aliases.agent_loop_output_aliases()` 生成，并通过 framework 的通用 `output_aliases` metadata 复制，不把 daily 命名规则写入 framework。

artifact publisher 也进入命名空间优先输出读取阶段：发布器只能通过 `daily_intelligence.output_projection` 的 `daily_output_value()` / `daily_output_contains()` 消费 `sources.*`、`evidence.*`、`quality.*`、`report.*`、`agent.feedback.*` 和 `agent.<label>.loop.*`，legacy key 只作为该 projection 内部的兼容兜底；发布器不得直接导入 `DAILY_BUFFER_ALIASES` 或重新维护 dotted/legacy 分支。对外 artifact key、manifest key 和文件路径继续保持现有稳定命名，例如 `quality_result.json`、`source_recollection/execution_report.json` 和 `agentic/agent_feedback_summary.json`。

daily run service、persistence、memory ingestion 和 board output attachment 不应各自维护 dotted/legacy 分支。服务层消费 daily workflow output 前，必须通过 `daily_intelligence.output_projection` 的统一 helper 做命名空间优先投影：

- `daily_output_value()` / `daily_output_contains()`：业务层 output accessor，统一执行 dotted-first、legacy fallback。
- `project_daily_output_for_persistence()`：只为落库 record 输入投影 persistence 所需 canonical key，不补齐无关 legacy 字段；该 projection 已切到 `NAMESPACED_ONLY`，不再从 legacy-only daily output key 构造 persistence 输入。
- `project_daily_output_for_board_attachment()`：只为 board attachment 投影 signals/source/evidence 输入 key；board 产出的 `board_outputs` 和 `cross_board_output` 再作为正式结果字段合并回 run output；该 projection 已切到 `NAMESPACED_ONLY`，不再从 legacy-only daily source/evidence output key 构造 board 输入。
- `project_daily_output_for_memory_ingestion()`：只为 memory ingestion 投影 report、evidence、quality decision 和 request/topic 所需 canonical key，不把 source ranking、agent feedback 或其它 daily runtime 字段带入 memory 消费面；该 projection 已切到 `NAMESPACED_ONLY`，不再从 legacy-only daily output key 构造 memory 输入。
- `project_daily_output_for_run_inspection()`：只为 run inspection 的 quality preview / lineage 投影 report、quality、citation、support matrix、candidate claims 和 verified findings 所需 canonical key，不把整份 runtime output 当作业务视图；该 projection 已切到 `NAMESPACED_ONLY`，不再从 legacy-only daily output key 构造 quality preview / lineage。
- `ensure_legacy_daily_output_aliases()`：只在公开 `RunResult.output` 需要保持历史兼容字段时原地补齐 legacy key，不作为下游服务调用的前置条件。
- `project_daily_output_for_legacy_consumers()`：仅作为历史兼容 helper 保留；新增服务消费面必须优先定义专用 projection，避免 consumer 直接理解 daily alias 表或接收整份 runtime output。

`DailyOutputProjectionReadPolicy` 用于显式标注 projection 的读取策略：persistence、memory ingestion、board attachment 和 run inspection 专用 projection 已切到 `NAMESPACED_ONLY`；`NAMESPACED_WITH_LEGACY_FALLBACK` 只保留在公开 output accessor 与历史兼容 helper 中，不得作为新增服务消费面的默认策略。

interfaces 可以调用这些 business projection helper，但不得在接口服务里复制 `DAILY_BUFFER_ALIASES` 或手写 `report.final -> final_report` 这类映射。memory 和 board 通用服务继续消费 canonical legacy 字段；daily workflow 的命名空间迁移规则只留在 daily workflow business 边界内。

run inspection 读取 manifest output 构建 quality preview / lineage 时，也必须先判断 workflow 是否属于 daily family，再调用 `project_daily_output_for_run_inspection()` 生成业务消费视图。inspection 可以保留原始 output key 作为调试预览，但质量决策、route、citation check、support matrix、candidate claims、verified findings 和 report id 只能从投影后的业务视图读取；接口层不得重新实现 daily key fallback，也不得调用泛化 legacy consumer projection。

report quality API 不应在接口层猜测 `report_json` 或 repository quality record 的历史形状。`business.layers.output.report_quality_projection` 负责从 `quality_trace`、旧 `quality` / `quality_gate` / `editor_review` / `quality_metrics` 字段，以及 `QualityResultRecord.payload` 中投影正式质量视图；`ReportApplicationService` 只负责读取 repository 记录、调用 projection，并把 lineage summary 组合到响应里。后续如果质量记录模型继续演进，应扩展该业务 projection 或正式 record model，不要在接口服务里新增结构分支。

## Persistence Record Construction 边界

持久化 record 构造属于 storage adapter 边界，但它只能消费上游 application service 已投影好的 canonical workflow output。

- `infrastructure.storage.persistence.records` 定义正式 storage record 模型，例如 `WorkflowRunRecord`、`ReportRecord` 和 `RunPersistenceBatch`。
- `infrastructure.storage.persistence.record_inputs` 定义 `RunPersistenceInput`，显式列出落库构造会消费的 canonical workflow output 字段；`run_persistence_input_from_output()` 只消费调用方传入的 canonical view，不理解 daily dotted key。
- `infrastructure.storage.persistence.record_builders` 负责把 `RunPersistenceInput` 转成 workflow/report/source/evidence/claim/quality records；旧 `*_from_result()` API 只作为 compatibility projection 入口保留。
- `infrastructure.storage.persistence.local_json_adapter` 承载本地 JSON adapter 和 record 文件读写细节。
- `infrastructure.storage.persistence.repository` 只保留 repository protocol、环境选择和 `persist_run_result()` / `persist_run_input()` 编排，不再内联 adapter 实现或 report/quality/source/evidence/claim 字段拼装。

daily workflow 的 dotted key 迁移规则仍属于 business daily output projection；persistence 不得重新维护 `report.final -> final_report`、`quality.result -> quality_result` 这类 alias 表。需要落库前，由 `DailyRunApplicationService` 调用接口层 `daily_persistence_projection`，先使用 business projection 生成 persistence-only canonical view，再构造 `RunPersistenceInput` 并通过 `persist_prepared_input()` 落库。这样 storage 层不依赖 `business`，daily service 也不需要为了 persistence 提前原地写回 legacy key。

`source_errors` / `sources.errors` 可以在兼容入口接收 legacy dict payload，但业务逻辑消费前必须通过 `business.foundation.models.source_error_normalization.normalize_source_errors()` 归一化为 `SourceError`，不得在业务分支里继续使用 `hasattr()` / `dict.get()` duck typing。daily 旧导入路径只作为兼容 re-export 保留。

## Quality Gate 边界

daily intelligence 的 `quality_gate_step.py` 是 workflow adapter，只负责读取 report draft、evidence、verified findings、quality events、memory/historian context 和 injected memory repository，然后组装 `DailyQualityGateInput`。

`quality_gate_usecase.py` 只编排三类服务：`DailyQualityGateContextService` 加载正式运行上下文，`DailyQualityGateEvaluationService` 生成质量评估结果，`quality_gate_outputs.py` 构建 final/blocked report、markdown、quality result alias 和 memory quality metadata 投影。usecase 不再承载 rewrite、bypass 或 human review 的业务分支。

memory context、historian context 和 memory quality result 的组合由 `quality_gate_context.py` 的 `DailyQualityGateContextService` 发起，并委托 `quality_context_projection.py` 的 `DailyQualityContextProjectionService` 构建。显式 `historian_context` 优先；从 report 或 memory metadata 读取 historian 只作为旧数据兼容入口，不能散落在 quality gate usecase 中。

质量评估、rewrite 尝试、non-social-media bypass 和 human review 路由由 `quality_gate_evaluation.py` 的 `DailyQualityGateEvaluationService` 承载。critical memory issue 判定收敛到 `memory_quality.py` 的 `has_critical_memory_quality_issue()`，避免在 usecase 或 step 中重新扫描 memory quality payload。

quality gate 的单次运行观测指标由 `quality_observability.py` 构建，输出可聚合的 count/rate 字段（例如 block、rewrite、human review、memory conflict）。workflow step 不维护历史窗口；窗口聚合应由 artifact/storage/monitoring 层消费这些正式指标完成。

新增 quality gate 规则时，应优先扩展 `DailyQualityGateInput`、`QualityGateContext`、`QualityGateEvaluation` 或拆分 quality routing/output 子服务，不要把业务分支重新写回 workflow step。

non-social-media bypass 判定统一由 `quality_gate_policy.assess_non_social_media_bypass()` 返回，quality gate 和 report finalization 只能消费该 assessment，不应各自重新判断或拼接 bypass 事件字段。

## Report Finalization 边界

agentic daily workflow 的 `finalize_report_step.py` 是 workflow adapter，只负责读取 `request`、draft、quality、evidence 和 agent feedback buffer key，并组装 `DailyReportFinalizationInput`。

最终报告发布、blocked / human review 路由、rewrite 结果校验、quality result、artifact refs、agent feedback metadata 和补源质量策略投影由 `report_finalization.py` 的 `finalize_daily_report()` 承载。该 usecase 不依赖 `framework.workflow`，因此可以脱离 `DataBuffer` 单独测试。

人工审核后的恢复决策由 `human_review_resume.py` 投影为 `DailyHumanReviewResumeRoute`：approve 映射到 `final`，reject 映射到 `blocked`，modify / modified / modifications 映射到 `rewrite`，并在 workflow 声明可消费 route key 时写入 `buffer_updates`、`resume_metadata` 和命名空间 quality key。`ApprovalResumeApplicationService` 只负责在 daily workflow resume 前调用该业务投影；framework runner 只理解通用 `resume_next_step_id`，通过 `ResumeMode.FROM_STEP` 恢复到声明过的目标 step，不理解 daily 专属 route 规则。approve / reject 通常回到 `finalize_report`，rewrite 可以回到 `writer_agent` 重新生成后续草稿、校验和反馈链路。

报告草稿输入归一化、claim grounding 归一化、以及草稿引用来源是否落在 evidence bundle 内的边界检查由 `report_draft_normalization.py` 承载。`report_finalization.py` 只消费归一化后的 draft 和明确的 source-boundary 结果，不再内联这些输入清洗 helper。

finalization 阶段的 report quality summary、quality gate metrics、quality result 和 human review request 由 `report_quality_outputs.py` 构建。`FinalReport`、`BlockedReport`、markdown、命名空间 alias、agent feedback metadata 和补源质量摘要投影由 `report_finalization_outputs.py` 构建。`report_finalization.py` 负责选择发布/阻断/重写/人工审核路线，并把这些输出 builder 组合进最终返回值。

后续新增 finalization 规则时，应优先扩展 `DailyReportFinalizationInput` 或拆分 report finalization 子服务，不要把业务决策重新写回 workflow step。

## Daily Agent Tool 边界

daily agent 工具由 `agent_tools.py` 只负责注册到 framework `ToolRegistry`；实际 evidence search、source metadata、citation validation 和 source-bounded section draft 逻辑由 `agent_tool_service.py` 的 `DailyAgentToolService` 承载。工具只读取当前 workflow 输入，不得自行抓取外部来源，也不得生成 evidence bundle 之外的 source URL。

writer/editor 若需要草稿或重写辅助，应调用 `daily.section_draft` 生成带 `sources`、`evidence_ids` 和 `claim_grounding` 的 section skeleton，再由 agent 输出层接受 schema 与 evidence boundary 校验。

## Agent Feedback 边界

Agent 间反馈不应隐藏在各 agent output 的自由形态字段里，也不应由 `finalize_report` 反向猜测。

- verifier/editor 对 writer、human review 或 publication gate 的反馈先归一化为 `agent_feedback_events`。
- analyst source recollection 输入必须写入 `DailyAgentFeedbackEvent.evidence_gaps`、`source_recollection_requests` 和 `missing_information` 正式字段；新建反馈事件不得再把这些字段双写进 `event.metadata`。旧 `event.metadata` 只作为历史 payload 投影入口。`DailySourceRecollectionService` 只读取这些正式字段，不再从 feedback event metadata 反推补源 profile 输入。
- 聚合指标写入 `agent_feedback_summary`，供 final report、blocked report、quality result 和 artifact manifest 使用。
- `DailyAgentFeedbackPolicyService` 将 feedback events 转换为 `policy_recommendations`，作为后续 rewrite / human review / block routing 的正式策略输入。
- `DailyAgentFeedbackRoutingService` 消费 `agent_feedback_summary` 和上一轮 `agent_feedback_loop_state`，生成新的 loop state 与 `agent_feedback_route`；对 verifier 阶段发现的问题最多触发一轮 bounded writer rewrite，第二次仍要求 rewrite 时进入 finalize/quality policy 路径，不允许无限 agent 循环。
- analyst 只能通过显式 `analysis_result.evidence_gaps`、`source_recollection_requests` 或 `missing_information` 生成 `daily.source_recollect` recommendation；collector 不从自然语言 notes 中猜测缺口。`collect_agent_feedback` 只负责调用 `DailySourceRecollectionService` 和 `DailySourceRecollectionExecutionService`，由 application service 将 recommendation 转换为正式 `DailySourceRecollectionProfile` 与 `DailySourceRecollectionExecutionPlan`，再通过 `source_recollection_profile` / `sources.recollection_profile` 和 `source_recollection_execution_plan` / `sources.recollection_execution_plan` 交给 `recollect_sources` 与后续 planner 消费；feedback step 不直接抓源，也不把 loop state 或 query 统计塞进 `metadata`。
- `DailySourceRecollectionExecutor` 必须输出 `source_recollection_execution_report` / `sources.recollection_execution_report`，用正式 `DailySourceRecollectionExecutionReport` 承载 task 状态、fetch request/result、raw item 和 error 计数；planner、artifact publisher 和后续 quality gate 只能消费该报告，不从 `source_events` 或 raw item `metadata` 反推补源质量。
- `DailySourceRecollectionExecutor` 的 task/item 运行期计数由 `SourceRecollectionTaskItemTracker` 承载；`DailySourceRecollectionArtifactProjector` 只负责把 plan/task context 投影到 fetch request、raw item 和 skipped source metadata，供 artifact 与历史兼容使用。
- `DailySourceRecollectionQualityService` 消费 execution report 并输出 `source_recollection_quality_assessment` / `sources.recollection_quality_assessment`，其中包含阈值结果、decision、severity、route 和 recommended_action；executor 只负责调用该 service 并写 buffer，artifact publisher 只投影 assessment，不重新实现阈值策略。
- `select_source_recollection_finalization_policy()` 在 strict quality gate 场景消费该 assessment；当补源结果不足时，`finalize_daily_report()` 将发布路线调整为 `human_review`，并把补源质量摘要投影到 `quality_result`、`human_review_request` 和 blocked report metadata。
- `finalize_daily_report()` 在 strict quality gate 场景消费这些 recommendation，并可将发布路线调整为 blocked / human review / rewrite；non-social-media bypass 仍由统一 bypass policy 优先决定。
- 当前闭环雏形允许 writer 根据 verifier feedback 做一次 source-bounded rewrite，也允许 analyst evidence gap 触发一次 planner/source recollect route，并由 `DailySourceRecollectionExecutor` 消费 `DailySourceRecollectionExecutionPlan` 执行 source fetch，随后重新进入 normalize / deduplicate / rank / evidence pipeline，再回到 planner。editor 产出的 rewrite / edited draft 仍由 finalization 消费。

## BoardServiceBase 边界

`BoardServiceBase` 是 board 门面，只保留：

- context 解析和公开调用入口；
- board-specific policy hook；
- 旧调用方兼容方法；
- 对 `BoardServiceRuntime` 装配结果的兼容属性暴露。
- `BoardWorkflowTrace.board_focus` 是 workflow 结果的正式焦点字段；`BoardWorkflowResult.metadata["board_focus"]` 仅作历史兼容投影，不应作为新代码的内部状态入口。

通用服务装配已移动到 `business/boards/application/service_runtime.py`。
selection、quality、references 等领域规则位于 `business/boards/domain/`。
`business/boards/services/` 中同名模块只作为兼容导出，不再是新逻辑落点。

## Productized 用例边界

`ProductizedBoardUseCases` 是工作流应用入口，负责协调专用服务，不承载具体业务算法。

- `ProductizedBoardPorts` 是 productized 用例消费 board 门面的正式端口投影，只暴露 signal selection、board run result 构建和 board name；classification / output 等专用服务不得保存或继续下传完整 `BoardServiceBase`。
- `ProductizedEvidenceService` 委托 `BoardEvidenceAssemblyService` 生成 evidence refs/items，并把正式中间结果写入 `ProductizedRunState`。
- `ProductizedRankingService` 委托 `BoardSignalRankingService` 排序 signals，并返回正式 `ranked_signals` step 输出。
- `ProductizedBoardOutputBundleBuilder` 负责 artifact-facing metadata 合并，并生成 `ProductizedBoardOutputBundle`。
- `ProductizedBoardOutputBundleBuilder` 不再把完整 `ProductizedRunState` 合并进 `BoardRunResult.metadata`；运行态通过 `ProductizedBoardOutputBundle.run_state` 和 workflow `productized_run` key 传递。
- `ProductizedBoardOutputBundle.report_summary` 是 report-writing skill 输出摘要的正式投影，并通过 workflow `report_summary` key 传给订阅用例；旧 `board_output.metadata.report.summary` 只作兼容兜底。
- `ProductizedRunStateMetadataProjector` 负责把 run state 投影成 artifact-facing 或历史兼容 metadata；`ProductizedRunState` 本身只作为正式运行态模型，旧 metadata 方法仅作薄兼容入口。
- `ProductizedImprovementWorkflowService` 负责 recommendation、proposal、policy experiment application 和 report 输出协调。
- `ProductizedImprovementMeasurementService` 负责 measurement snapshot 和 delta 计算，主算法消费 `ProductizedImprovementMeasurementInput`，其中 `deduplication_result` 是正式字段；productized workflow 必须优先调用 `measure_productized()`，旧 `board_run_result.metadata` 读取只保留在 `measurement_legacy.py` / compatibility constructor 中。

跨 step 的运行态中间结果使用 `ProductizedRunState`。`metadata` 只保留对外 artifact 和历史兼容字段。

## Metadata 使用规则

`metadata` 只能承载对外输出需要的摘要、序列化快照或兼容字段。跨 step 的运行时中间结果必须使用正式 buffer key 或模型。

本轮新增的正式字段：

- `BoardRunResult.board_output`：显式承载 board output payload。
- `BoardRunResult.board_intelligence`：显式承载 board focus、policy profile 和 feature weight 的正式运行态摘要。
- `BoardRunResult.pipeline_snapshot`：显式承载 pipeline snapshot，类型为 `BoardRunPipelineSnapshot`。
- `BoardRunResult.report_payloads`：显式承载从 board output 提取的 report payload。
- `BoardRunResult.metadata["board_output"]`：仅作为历史兼容字段保留。
- `ProductizedRunState`：承载 skill traces、extracted entities、evidence refs/items、deduplication result、trend analysis 和 improvement context。
- `ProductizedBoardOutputBundle.report_summary` / `report_summary` buffer key：承载报告摘要，订阅服务必须优先消费该正式字段，不得从 board output metadata 反推摘要。
- `DailySourceRecollectionExecutionReport`：承载补源执行 task 状态、selected sources、fetch request/result、raw item 与 error 计数，并通过 `source_recollection_execution_report` / `sources.recollection_execution_report` 传递。
- `DailySourceRecollectionQualityAssessment`：承载补源质量阈值、decision、route 和 recommended_action，并通过 `source_recollection_quality_assessment` / `sources.recollection_quality_assessment` 传递。
- `ManualSourceRecords`：承载 manual source 的 curated records payload，作为 `SourceConnectorRuntimeOptions.manual_records` 传递；`metadata["records"]` 只在 options 投影边界和 connector 历史兜底里出现。
- `SourceConnectorRuntimeOptions`：承载 daily source connector 运行参数，集中投影 connector-specific legacy metadata 与 request topic，包括 manual records、arXiv query、GitHub repository/query/collection mode/discussion category、Hacker News story list、Reddit listing/time range 选择和 community tag/site；source collection / recollection / dispatcher / fetch request 只消费该正式 view。
- `SourceFetchRequest.connector_name`：承载 source fetch 的正式 connector dispatch 名称；`metadata["connector_name"]` 只作为历史序列化和 artifact 兼容字段。

新代码应优先读取正式字段，例如 `BoardRunResult.board_output` 和 `productized_run`，不要从 `metadata` 反向推断内部状态。
`BoardRunApplicationResult` 是 board run 组装阶段的正式 application result model；
`BoardRunMetadataBuilder` 只负责把它投影成旧调用方需要的 metadata 兼容字段。

## Improvement 边界

improvement 主流程是：

`feedback -> learning signal -> recommendation -> policy experiment profile -> applied policy experiment -> measurement`

`ImprovementProposalBuilder` 将 recommendation 转换为 `policy_experiment` proposal 和 `PolicyExperimentProfile`。
新 proposal 使用 `policy_experiment_parameters` 作为正式参数字段；`proposed_patch` 只作为历史兼容读取入口，不再由新代码生成。
`ImprovementApplier` 返回 `PolicyExperimentApplicationContext`，主字段为：

- `applied_policy_experiments`
- `skipped_policy_experiments`
- `proposal_ids`
- `measurement_plan`

`applied_overrides` 和 `skipped_overrides` 只作为历史兼容属性保留，内容等同于 policy experiment 结果。
旧 `proposed_patch` 字段只用于读取历史持久化数据；新 proposal 不再生成 patch payload。
`SelfImprovementReport` 和 productized improvement 输出会显式投影 `policy_experiment_profiles` / `policy_experiment_profile_ids`，作为比 `applied_overrides` 更正式的策略实验视图。

Weekly intelligence 的 improvement 逻辑由 `business/boards/cross_board/weekly_improvement.py` 承载：

- `WeeklyImprovementRecommendationService` 消费 `weekly_quality` 和 `weekly_trends`，生成 `ImprovementRecommendation` 与 `PolicyExperimentProfile`。
- `WeeklyImprovementReport` 对外输出 `recommendations`、`policy_experiment_profiles`、`policy_experiment_profile_ids`、`risks` 和 `next_actions`。
- `business/boards/cross_board/workflows/weekly_intelligence/weekly_improvement.py` 只保留历史导入路径兼容，不再承载推荐规则。
- Weekly 新输出不得生成 `*_override` target type、override 风险文案或 `proposed_patch`；如旧消费者仍需要 override 视图，必须在兼容层由 policy experiment 结果投影。

## 禁止依赖

- `framework/` 不得导入 `business`、`interfaces` 或具体 `infrastructure`。
- `business/foundation/` 不得导入 `business.layers` 或 `business.boards`。
- `business/layers/` 不得导入 `business.boards`。
- `business/boards/` 不得导入具体存储 adapter。
- workflow step 模块不得直接导入 lower-layer pipeline、subscription/improvement/output 构造器来承载业务逻辑。
