## 1. OpenSpec

- [x] 1.1 创建 `community-pulse-board-frontend-v1` proposal、design、specs 和 tasks。
- [x] 1.2 执行 `openspec validate community-pulse-board-frontend-v1 --strict`。

## 2. Types, Data, And API

- [x] 2.1 扩展 Community TypeScript 类型，加入 PRD 对齐的 signal、source、sentiment、cluster、list/detail payload。
- [x] 2.2 扩展 Community adapter/filter/server-data，从现有 artifact/topics 派生 signals、clusters、facets、metrics 和 detail。
- [x] 2.3 实现 PRD 查询参数、source/sentiment 规范化、period 过滤、hot/newest/controversial/adoption 排序和 cursor 分页。
- [x] 2.4 新增 `/api/community/signals` 和 `/api/community/signals/:id` BFF route，并保留现有 topic API 兼容。
- [x] 2.5 更新 Community API client，使用 signals list/detail 作为新版页面数据源。

## 3. Community Pulse UI

- [x] 3.1 升级 `/community` 页面为 PRD 布局：Hero、Filter Bar、Sidebar、Signal Stream、Hot Discussion Card、Debate Cluster。
- [x] 3.2 添加 `/community?signal=<id>` 详情抽屉，展示 signal、evidence links、相关论文/项目/新闻和空态。
- [x] 3.3 更新首页 Community Pulse 模块文案、导航文案和 `/news?source=community` 兼容跳转。
- [x] 3.4 修复 Community 相关用户可见硬编码乱码。

## 4. Documentation And Tests

- [x] 4.1 更新 PRD-06 状态、入口说明和 MVP 数据源说明。
- [x] 4.2 添加或更新 adapter/filter/server-data/API route 单元测试。
- [x] 4.3 添加或更新 UI 组件测试，覆盖空态、筛选、热议卡、信号行、争议簇和详情抽屉。
- [x] 4.4 更新 E2E 导航覆盖 `/community`、首页入口和 `/news?source=community`。

## 5. Validation And Commit

- [x] 5.1 运行 OpenSpec validation。
- [x] 5.2 运行 frontend typecheck、community 测试、build 和 targeted E2E navigation spec。
- [x] 5.3 检查 git 状态并提交完成变更。
