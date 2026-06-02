# 业务层边界

本文说明 NewsRoom `business/` 层当前的职责边界。它补充
`docs/architecture/framework-boundaries.md`：`framework/` 只能承载领域无关运行时能力，
不能导入 `business`、`interfaces` 或具体 `infrastructure`。

## 分层职责

- `business/foundation/`：业务基础模型、枚举、注册表、策略快照、反馈学习模型和 Skill 内容包。它不能导入 `business.layers` 或 `business.boards`。
- `business/layers/`：可复用的业务处理流水线，包括 signal、extraction、relation、analysis、output、memory。它可以依赖 foundation，但不能依赖 boards。
- `business/boards/services/`：board 通用 application/domain service。selection、pipeline runner、quality、artifact/evidence/memory refs、run result 构建和 output annotation 放在这里。
- `business/boards/productized/`：productized board workflow 的应用用例和专用服务。这里承载技能 payload、证据构建、排序、趋势输入、质量检查输入、输出 bundle、反馈学习、improvement 和 artifact metadata。
- `business/boards/<board_type>/`：单个 board 的策略、presenter、ranking rules、runner 和 workflow 入口。它只承载 board 特化行为，不放通用 selection、pipeline、quality、artifact refs 或 feedback/improvement 逻辑。

## Workflow Step 边界

Productized workflow step 的职责是：

1. 从 workflow buffer 读取声明过的 key。
2. 调用 `ProductizedBoardUseCases` 的对应方法。
3. 返回声明过的输出 key。

Step 不直接执行 signal selection、ranking、evidence、quality、feedback、improvement、subscription 或 output bundle 构建逻辑。新增业务逻辑应进入 `business/boards/productized/` 的服务，或进入 `business/boards/services/` 的通用 board service。
Step 实例只保留 `board_type` 和 `ProductizedBoardUseCases`，不保存底层 service/runtime 依赖；workflow spec 的 `read_keys` 只声明对应 step 实际读取的 buffer key。

## BoardServiceBase 边界

`BoardServiceBase` 是 board 门面。它保留：

- context 解析；
- 通用服务装配；
- board-specific policy hook；
- 旧调用方兼容的公开方法。

以下职责已拆到独立服务：

- `BoardSignalSelectionService`：coerce/filter/sort board signals。
- `BoardPipelineRunner`：运行 extraction、relation、analysis、output pipeline，并调用 output annotation 与 board output postprocess hook。
- `BoardOutputAnnotationService`：写入 BoardOutput 的标准 annotation。
- `BoardQualityService`：构建 board run quality snapshot 和 feedback candidates。
- `BoardRunReferenceService`：构建 trace、manifest、artifact、evidence、memory refs。
- `BoardRunMetadataBuilder`：生成正式 board run metadata payload，并集中隔离旧 pipeline metadata 兼容字段。
- `BoardRunResultBuilder`：组装 `BoardRunResult`，生成 pipeline snapshot，并委托 metadata builder 生成 metadata payload。

`BoardServiceBase` 不再直接承载 pipeline 执行细节或默认 run result metadata 拼装。

## Board Type 专用服务边界

单个 board 的复杂业务可以拆到该 board 目录下的专用 application service，但不应堆在 `BoardServiceBase` 或具体 board service 门面里。

Cross-board 当前边界如下：

- `CrossBoardGraphIntelligenceService`：从已处理的 signals、extraction results、relations、analysis 和 board outputs 构建 graph、paths、graph quality 和 graph insights。
- `CrossBoardRunResultEnricher`：把 cross-board insights/graph result 附加回 `BoardRunResult`，集中处理 cross-board quality merge 和 feedback events；learning signals、policy candidates 和 regression guard results 通过 foundation 的 `build_runtime_quality_closure` 生成。
- `CrossBoardService`：保留公开入口和旧方法委托，不直接承载 graph/path/quality/feedback/policy candidate 组合逻辑。

## Productized 用例边界

`ProductizedBoardUseCases` 是工作流应用入口，不直接持有大段输出拼装逻辑。专用服务包括：

- `ProductizedEvidenceService`：构建证据 refs/items，并把正式 evidence 中间结果写入 `ProductizedRunState`。
- `ProductizedSignalPreparationService`：解析 productized run context、coerce raw signals、运行 source reliability skill，并写入 `ProductizedRunState`。
- `ProductizedSignalClassificationService`：调用 board selection 门面并返回正式 `board_signals` step 输出。
- `ProductizedEntityExtractionService`：运行 entity-extraction skill、生成正式 extracted entities 中间结果，并写入 `ProductizedRunState`。
- `ProductizedDeduplicationService`：运行 event-deduplication skill、生成 deduplication result，并写入 `ProductizedRunState`。
- `ProductizedRankingService`：排序 productized signals，并返回正式 `ranked_signals` step 输出。
- `ProductizedTrendEventService`：构建 trend-analysis 技能输入。
- `ProductizedTrendAnalysisService`：运行 trend-analysis skill、生成 trend analysis 中间结果，并写入 `ProductizedRunState`。
- `ProductizedQualityService`：构建 evidence-checking 输入并合并质量摘要。
- `ProductizedQualitySummaryService`：运行 evidence-checking skill、生成正式 quality summary 输出，并写入 `ProductizedRunState`。
- `ProductizedReportWritingService`：运行 report-writing skill，生成报告 markdown payload。
- `ProductizedBoardOutputBundleBuilder`：集中合并 artifact-facing metadata，并生成 `ProductizedBoardOutputBundle`。
- `ProductizedBoardOutputService`：协调 board run result、报告写作和 output bundle，不直接承载 report skill 或 metadata 拼装细节。
- `ProductizedSubscriptionService`：构建 subscription payload 与 delivery plan，保持 workflow 输出键兼容。
- `ProductizedFeedbackLearningService`：从 board run result 收集反馈和 learning signals。
- `ProductizedImprovementWorkflowService`：从质量、反馈、订阅结果生成 recommendation、proposal、applied experiment 和 measurement。
- `ProductizedArtifactMetadataService`：生成 artifact manifest metadata，并返回 workflow artifact step 输出键。

跨 step 的运行态中间结果使用 `ProductizedRunState`；board output 步骤使用 `ProductizedBoardOutputBundle` 显式返回 workflow 输出键。

## Improvement 边界

improvement 流程方向是：

`feedback -> learning signal -> recommendation -> policy experiment profile -> applied policy experiment -> measurement`

`FeedbackLearningService` 负责 feedback 去重与 learning signal 构建。`LearningSignalRecommendationBuilder` 和 `QualitySummaryRecommendationBuilder` 分别负责从 learning signal 与 quality summary 生成 recommendation；`ImprovementRecommendationBuilder` 只做来源 builder 的协调门面，并负责合并与去重 recommendation。`ImprovementProposalBuilder` 负责把 recommendation 转成 `policy_experiment` proposal 和 `PolicyExperimentProfile`。`ImprovementApplicationService` 负责从 proposal store 选择当前 board 的 proposal 并应用已批准实验。`SelfImprovementReportBuilder` 负责风险摘要、next action 和 report payload 组装。Board 层的 improvement service 只负责调用这些 service/builder、保存 proposal 和返回报告。

新 proposal 不再生成 patch payload；它携带 `PolicyExperimentProfile`，用于描述目标、参数、理由、建议动作和度量指标。`applied_overrides` 作为历史 artifact/output 键暂时保留，但其内容是 applied policy experiment。旧手工 proposal 的 patch 数据只在读取历史记录时转换为实验参数。

## Metadata 使用规则

`metadata` 只能承载对外输出需要的摘要、序列化快照或兼容字段。跨 step 的运行时中间结果应使用正式 buffer key 或模型。

Productized workflow 使用 `ProductizedRunState` 承载：

- skill traces；
- extracted entities；
- evidence refs/items；
- deduplication result；
- trend analysis；
- improvement context。

artifact-facing board output metadata 由 `ProductizedRunState.board_output_metadata()` 显式生成，只暴露当前 artifact 兼容所需字段。内部流程优先读取 `productized_run`，不通过 `board_output.metadata` 反向取中间状态。

## 禁止依赖

- `framework/` 不得导入 `business`、`interfaces`、具体 `infrastructure`。
- `business/foundation/` 不得导入 `business.layers` 或 `business.boards`。
- `business/layers/` 不得导入 `business.boards`。
- `business/boards/` 不得导入具体存储 adapter。
- workflow step 模块不得直接导入 lower-layer pipeline 或 subscription/improvement/output 具体构造器来承载业务逻辑。
