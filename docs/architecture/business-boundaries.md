# Business Boundaries

本文档描述 NewsRoom `business/` 层的当前边界。它补充 `docs/architecture/framework-boundaries.md`：`framework/` 仍然只拥有领域无关运行时，不能导入 `business`、`interfaces` 或具体 `infrastructure`。

## 分层职责

- `business/foundation/`：业务基础模型、枚举、注册表、策略快照、反馈学习模型和 Skill 内容包。它不能导入 `business.layers` 或 `business.boards`。
- `business/layers/`：可复用的业务处理流水线，包括 signal、extraction、relation、analysis、output、memory。它可以依赖 foundation，但不能依赖 boards。
- `business/boards/services/`：board 应用服务和 domain service。selection、quality、artifact/evidence/memory refs、run result 构建放在这里，供 board service 门面和 workflow 使用。
- `business/boards/productized/`：productized board workflow 的应用用例。这里编排 buffer 输入之外的业务动作，例如技能 payload 构造、证据构建、排序、趋势输入、质量检查输入、反馈学习、improvement、artifact metadata。
- `business/boards/<board_type>/`：单个 board 的策略、presenter、ranking rules、runner 和 workflow 入口。它只承载 board 特化行为，不放通用 selection、质量、artifact refs 或 feedback/improvement 通用逻辑。

## Workflow Step 边界

Productized workflow step 的职责是：

1. 从 workflow buffer 读取声明过的 key。
2. 调用 `ProductizedBoardUseCases` 的对应方法。
3. 返回声明过的输出 key。

Step 不直接执行 signal selection、ranking、evidence、quality、feedback、improvement 或 subscription 构建逻辑。新增业务逻辑应进入 `business/boards/productized/` 的服务或 `business/boards/services/` 的 board service。

## BoardServiceBase 边界

`BoardServiceBase` 是 board 门面。它保留：

- context 解析；
- pipeline 调用顺序；
- board-specific policy hook；
- 向旧调用方兼容的公开方法。

以下职责已拆到独立服务：

- `BoardSignalSelectionService`：coerce/filter/sort board signals。
- `BoardQualityService`：board run quality snapshot 和 feedback candidates。
- `BoardRunReferenceService`：trace、manifest、artifact、evidence、memory refs。
- `BoardRunResultBuilder`：BoardRunResult 组装和 pipeline snapshot。
- `BoardOutputAnnotationService`：BoardOutput annotation。

## Improvement 边界

improvement 流程的方向是：

`feedback -> learning signal -> recommendation -> policy experiment profile -> applied policy experiment -> measurement`

新 proposal 不再生成 patch payload；它携带 `PolicyExperimentProfile`，用于描述目标、参数、理由、建议动作和度量指标。`applied_overrides` 作为历史 artifact/output 键暂时保留，但其内容是 applied policy experiment。旧手工 proposal 的 patch 数据只在读取历史记录时转为实验参数。

## Metadata 使用规则

`metadata` 只能承载对外输出需要的摘要、序列化快照或兼容字段。跨 step 的运行时中间结果应使用正式 buffer key 或模型。

Productized workflow 使用 `ProductizedRunState` 承载：

- skill traces；
- extracted entities；
- evidence refs/items；
- deduplication result；
- trend analysis；
- improvement context。

这些字段仍会被序列化进输出 metadata，供现有 artifact 和接口兼容，但内部流程优先读写 `productized_run`。

## 禁止依赖

- `framework/` 不得导入 `business`、`interfaces`、具体 `infrastructure`。
- `business/foundation/` 不得导入 `business.layers` 或 `business.boards`。
- `business/layers/` 不得导入 `business.boards`。
- `business/boards/` 不得导入具体存储 adapter。
- workflow step 模块不得直接导入 lower-layer pipeline 或 subscription/improvement 具体构造器来承载业务逻辑。
