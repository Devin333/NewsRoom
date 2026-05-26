## ADDED Requirements

### Requirement: Community Pulse route
系统 SHALL 以 `/community` 作为 Community Pulse Board 的主前台入口。

#### Scenario: 打开 Community Pulse
- **WHEN** 用户打开 `/community`
- **THEN** 页面展示 `Community Pulse` 前台阅读体验
- **AND** 页面包含 Hero、筛选栏、侧边 facets、信号流、热议信号和争议信号区域
- **AND** 空数据或降级数据不会导致页面崩溃

### Requirement: Community signals API
系统 SHALL 提供 PRD 对齐的 Community Signal BFF API，同时保留现有 topic API 兼容行为。

#### Scenario: 获取信号列表
- **WHEN** 用户请求 `GET /api/community/signals`
- **THEN** 响应 envelope 的 data 包含 `items`、`clusters`、`facets` 和 `nextCursor`
- **AND** data 同时包含前台需要的 `metrics`、`dataState`、`source`、`generatedAt` 和 `notices`

#### Scenario: 获取信号详情
- **WHEN** 用户请求 `GET /api/community/signals/:id` 且信号存在
- **THEN** 响应 data 包含 `signal`、`relatedPapers`、`relatedProjects`、`relatedNews` 和 `evidenceLinks`

#### Scenario: 信号详情不存在
- **WHEN** 用户请求不存在的 `GET /api/community/signals/:id`
- **THEN** 响应为 404
- **AND** error code 为 `community_signal_not_found`

### Requirement: Community signal filtering and sorting
系统 SHALL 支持 PRD 查询参数并兼容旧分页参数。

#### Scenario: 使用 PRD 参数筛选
- **WHEN** 用户请求 signals API 并传入 `source`、`topic`、`sentiment`、`period`、`sort`、`q`、`limit` 或 `cursor`
- **THEN** 系统按对应来源、主题、情绪、时间、排序、搜索词和分页返回结果

#### Scenario: 使用兼容参数
- **WHEN** 用户使用旧 `page`、`pageSize` 或 `sort=trending`
- **THEN** 系统返回等价的分页和热度排序结果

### Requirement: Real artifact data only
系统 SHALL 从已有后端或本地 Community Pulse artifact 派生运行时内容，MUST NOT 使用运行时假数据填充信号。

#### Scenario: artifact 可用
- **WHEN** 后端或本地 `community_pulse` artifact 可用
- **THEN** Community Signal 列表和详情从 artifact 中派生公开字段
- **AND** 敏感字段和非 HTTPS 私密 URL 不会暴露给前台

#### Scenario: artifact 不可用
- **WHEN** 后端和本地 artifact 都不可用
- **THEN** signals API 返回空 items、空 clusters、空 facets 和明确 notices
- **AND** 页面展示空态而不是假数据

### Requirement: Community Pulse UI composition
前台 SHALL 显示 PRD 要求的热议卡、信号行、争议簇、基础筛选和详情抽屉。

#### Scenario: 渲染信号流
- **WHEN** signals 数据存在
- **THEN** 页面展示每条信号的标题、来源、发布时间、score/comments、sentiment、summary、topics、热度和关联论文/项目/新闻数量

#### Scenario: 打开详情抽屉
- **WHEN** 用户打开 `/community?signal=<id>`
- **THEN** 页面展示该信号的详情抽屉
- **AND** 关闭抽屉后 URL 回到 `/community` 并保留其他筛选参数

### Requirement: Portal and navigation entry
系统 SHALL 保留首页 Community Pulse 模块入口，并兼容 `/news?source=community`。

#### Scenario: 首页入口
- **WHEN** Portal 首页渲染
- **THEN** 用户能看到 `Community Pulse` 模块卡片
- **AND** 入口指向 `/community`

#### Scenario: news 参数兼容入口
- **WHEN** 用户打开 `/news?source=community`
- **THEN** 系统跳转到 `/community`
- **AND** 可映射的筛选参数被保留
