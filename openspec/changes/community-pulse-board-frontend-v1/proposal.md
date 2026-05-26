## Why

PRD-06 要求 Community Pulse 成为面向读者的社区信号观察前台模块，但现有 `/community` 更偏 topic 列表，尚未提供 PRD 要求的 signal stream、signals BFF API、热议卡、争议簇、详情抽屉和 `/news?source=community` 兼容入口。

## What Changes

- 将 `/community` 升级为 Community Pulse Board 主入口，展示 Hero、筛选栏、侧边 facets、Hot Discussion Card、Signal Row、Debate Cluster 和详情抽屉。
- 新增 `GET /api/community/signals` 和 `GET /api/community/signals/:id` BFF，并保留现有 `/api/community`、`/api/community/topics/:slug` 兼容路径。
- 从现有 `community_pulse-productized-board` 后端 artifact 和本地 `.newsroom/runs` artifact 派生 PRD 对齐的 Community Signal 数据，不引入运行时 mock 数据。
- 支持 PRD 查询参数：`source`、`topic`、`sentiment`、`period`、`sort`、`q`、`limit`、`cursor`，并兼容旧 `page/pageSize/trending` 用法。
- 保持首页 Community Pulse 模块入口，统一导航文案，并让 `/news?source=community` 跳转到 `/community`。
- 更新 PRD-06 状态和 MVP 数据源说明，补充测试与验证。

## Capabilities

### New Capabilities

- `community-pulse-board-frontend`: Community Pulse 前台页面、信号 API、筛选排序、详情抽屉、首页入口和真实 artifact 数据降级行为。

### Modified Capabilities

None.

## Impact

- 影响前端类型、Community adapter/filter/server-data/API client、`/community` 页面、`/news` 兼容入口、首页模块数据、导航配置、Community 相关测试和 PRD-06 文档。
- 不涉及 Python 后端 API、数据库迁移、实时社区采集、社交登录、评论发布、后台采集监控或新增运行时依赖。
