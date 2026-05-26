# PRD-01：NewsRoom 前台门户首页

版本：v1.0  
页面范围：`/`  
优先级：P0  
状态：已实现（已对齐）  
关联页面：`/papers`、`/news`、`/tech/repos`、`/community`、`/topics`、`/reports`

---

## 1. 产品背景

NewsRoom 目前已经拥有一个新的前台 UI 方向，即 `/papers` 页面。该页面具备较明确的前台产品特征：

- 面向内容阅读和发现。
- 信息密度高。
- 使用论文流、筛选、侧边分类、详情抽屉等模式。
- 视觉风格偏研究情报门户。

但是 `/` 首页仍然是旧后台页面，这会造成两个问题：

1. 用户打开首页时误以为产品是后台系统，而不是前台内容产品。
2. `/papers` 的新 UI 风格没有成为整个前台的统一基准。

因此需要重做 `/` 首页，将其定义为 NewsRoom 的前台门户。

---

## 2. 产品定位

### 2.1 一句话定位

NewsRoom 前台首页是 AI 技术情报、论文、开源项目、社区信号和跨板块证据链的统一入口。

### 2.2 目标用户

| 用户类型 | 需求 |
|---|---|
| AI 开发者 | 快速了解 AI 技术变化、开源项目、论文和实现 |
| Agent 开发者 | 追踪 agent 框架、工具调用、记忆、评测、工作流相关趋势 |
| 技术研究者 | 从论文和方法维度跟踪研究进展 |
| 产品/投资/战略人员 | 观察行业动态、公司动作、产品更新和生态变化 |
| 内容编辑/分析师 | 寻找热点、构建报告、组织证据链 |

---

## 3. 核心问题

当前 `/` 首页的问题：

1. 使用旧后台页面，不适合作为前台入口。
2. 模块语义偏后台监控，不符合内容门户定位。
3. 没有展示已经扩展的业务模块。
4. 用户无法从首页理解 NewsRoom 的核心能力。
5. `/papers` 与 `/` 的 UI 体系割裂。

---

## 4. 目标

### 4.1 P0 目标

- 删除 `/` 对旧后台组件的依赖。
- 将 `/` 改为前台门户首页。
- 首页展示以下模块：
  - AI News
  - Project Radar
  - Paper Radar
  - Community Pulse
  - Cross-board Evidence Graph
  - Reports
- UI 风格与 `/papers` 保持一致。

### 4.2 P1 目标

- 首页接入真实数据摘要。
- 支持按主题跳转。
- 支持最新论文、最新新闻、热门项目的混合展示。
- 支持模块卡片与导航联动。

### 4.3 P2 目标

- 首页支持个性化订阅。
- 首页支持用户关注主题。
- 首页支持跨板块推荐。
- 首页支持“今日技术情报简报”。

---

## 5. 非目标

本 PRD 不做：

- 不重做 `/studio`。
- 不设计后台监控台。
- 不做数据采集管理。
- 不做人工审核队列。
- 不做 workflow 编排 UI。
- 不做用户权限系统。
- 不做移动端 App。

---

## 6. 页面结构

### 6.1 页面整体结构

```text
/
├── Header
├── Hero
│   ├── 产品定位
│   ├── 一句话价值
│   └── 当前索引统计
├── Intelligence Boards
│   ├── AI News
│   ├── Project Radar
│   ├── Paper Radar
│   ├── Community Pulse
│   └── Cross-board Evidence Graph
├── Research Module
│   ├── Trending Papers
│   ├── Tasks
│   └── Methods
├── Latest Papers
├── Latest News
├── Trending Projects
├── Community Signals
└── Reports / Briefings
```

### 6.2 Hero 区

Hero 区需要明确告诉用户：

> 这里是 AI 技术情报前台，不是后台。

建议文案：

```text
AI 技术情报、论文、开源项目与社区信号的统一前台入口
```

副标题：

```text
NewsRoom 将 AI News、Project Radar、Paper Radar、Community Pulse 和跨板块证据链组织在同一个前台门户中，帮助用户从内容发现进入趋势、证据和报告。
```

Hero 右侧可展示当前系统索引状态：

| 指标 | 示例 |
|---|---|
| Papers indexed | 120 |
| Projects tracked | 86 |
| News sources | 34 |
| Community signals | 1.2k |
| Reports generated | 18 |

第一版可以只有 papers 真实数据，其他先使用占位或隐藏。

---

## 7. 模块卡片设计

### 7.1 AI News

入口：`/news`

展示内容：

- 官方更新
- 产品更新
- 融资并购
- 公司动态
- 政策和生态变化

卡片文案：

```text
追踪官方更新、产品动态、融资并购、生态变化与政策信号。
```

### 7.2 Project Radar

入口：`/tech/repos`

展示内容：

- GitHub 热门项目
- 新增项目
- Star 增长
- 技术栈
- 与论文/新闻的关联

卡片文案：

```text
追踪 GitHub 项目、开源实现、工程实践、增长趋势与技术采用。
```

### 7.3 Paper Radar

入口：`/papers`

展示内容：

- Trending Papers
- Tasks
- Methods
- Benchmarks
- Repo 实现

卡片文案：

```text
聚合论文、任务、方法、代码实现与研究前沿变化。
```

### 7.4 Community Pulse

入口：`/community`

展示内容：

- Hacker News
- Reddit
- GitHub Discussions
- X/社交媒体信号，第一版可不接
- 开发者评论摘要
- 争议和热议主题

卡片文案：

```text
观察社区讨论、开发者反馈、争议热点、传播路径与真实采用信号。
```

### 7.5 Cross-board Evidence Graph

入口：`/topics?view=evidence-graph`

展示内容：

- 论文 → 项目 → 社区讨论 → 新闻事件
- 技术路线演化
- 主题证据链
- 多源置信度

卡片文案：

```text
把 Paper、Project、Community、AI News 串成证据链和技术演进链。
```

---

## 8. 数据需求

### 8.1 首页数据模型

```ts
export type FrontendPortalSummary = {
  papers: {
    total: number
    latest: PortalPaperItem[]
    trending: PortalPaperItem[]
  }
  news: {
    total: number
    latest: PortalNewsItem[]
    topStories: PortalNewsItem[]
  }
  projects: {
    total: number
    trending: PortalProjectItem[]
  }
  community: {
    total: number
    hotSignals: PortalCommunitySignal[]
  }
  reports: {
    latest: PortalReportItem[]
  }
}
```

### 8.2 Paper Item

```ts
export type PortalPaperItem = {
  id: string
  title: string
  summary?: string
  authors?: string[]
  publishedAt?: string
  source?: string
  href: string
  tags?: string[]
}
```

### 8.3 News Item

```ts
export type PortalNewsItem = {
  id: string
  title: string
  summary?: string
  sourceName: string
  publishedAt: string
  category: "official" | "product" | "funding" | "policy" | "ecosystem" | "community"
  href: string
  confidence?: number
}
```

### 8.4 Project Item

```ts
export type PortalProjectItem = {
  id: string
  name: string
  owner: string
  repoUrl: string
  description?: string
  stars?: number
  starsDelta7d?: number
  language?: string
  topics?: string[]
  relatedPaperIds?: string[]
}
```

### 8.5 Community Signal

```ts
export type PortalCommunitySignal = {
  id: string
  title: string
  source: "hackernews" | "reddit" | "github" | "other"
  url: string
  score?: number
  comments?: number
  sentiment?: "positive" | "neutral" | "negative" | "mixed"
  relatedTopicIds?: string[]
}
```

---

## 9. 接口设计

### 9.1 首页聚合接口（后续 BFF）

```http
GET /api/portal/summary
```

Query：

| 参数 | 类型 | 说明 |
|---|---|---|
| locale | `zh` / `en` | 语言 |
| limit | number | 每类最多返回数量 |
| include | string | 可选：papers,news,projects,community,reports |

Response：

```json
{
  "papers": {
    "total": 120,
    "latest": []
  },
  "news": {
    "total": 340,
    "latest": []
  },
  "projects": {
    "total": 86,
    "trending": []
  },
  "community": {
    "total": 1200,
    "hotSignals": []
  },
  "reports": {
    "latest": []
  }
}
```

v1.0 暂不新增该接口，直接在 server component 中调用已有数据函数，例如：

```ts
const papers = await getPublishedPapers()
```

后续再升级为统一 BFF。

---

## 10. UI 规范

### 10.1 视觉基准

以 `/papers` 为主：

- 背景：浅米白 / 柔和灰绿
- 卡片：白底、浅边框、圆角
- 字体：紧凑但可读
- 信息流：标题 + 摘要 + 元数据
- 交互：hover 位移、轻微阴影、跳转箭头

### 10.2 不允许出现的旧后台视觉

首页不允许出现：

- 大量后台监控表格
- 运行状态仪表盘
- 采集器健康状态
- workflow run list
- artifact lineage
- human review queue
- admin settings

这些能力属于 `/studio`，不属于 `/`。

---

## 11. 路由设计

| 路由 | 页面 |
|---|---|
| `/` | 前台首页 |
| `/papers` | Trending Papers |
| `/papers/tasks` | Paper Tasks |
| `/papers/methods` | Paper Methods |
| `/news` | AI News |
| `/tech/repos` | Project Radar |
| `/community` | Community Pulse |
| `/topics` | Trends |
| `/topics?view=evidence-graph` | Evidence Graph |
| `/reports` | Reports |
| `/studio` | 后台工作台，非首页 |

---

## 12. 状态设计

| 状态 | 说明 | UI 表现 |
|---|---|---|
| loading | 首页聚合数据加载中 | skeleton 或局部 loading |
| empty | 某个模块暂无数据 | 显示空态说明和进入入口 |
| partial | 部分模块数据可用 | 可用模块正常展示，不可用模块显示提示 |
| error | 聚合接口失败 | 显示本地缓存或降级模块 |
| ready | 数据正常 | 完整展示 |

---

## 13. 验收标准

### 13.1 功能验收

- `/` 不再渲染旧后台。
- `/` 能看到前台 Hero。
- `/` 能看到五个模块卡片。
- 点击 AI News 进入 `/news`。
- 点击 Project Radar 进入 `/tech/repos`。
- 点击 Paper Radar 进入 `/papers`。
- 点击 Community Pulse 进入 `/community`。
- 点击 Evidence Graph 进入 `/topics?view=evidence-graph`。
- 首页能展示 latest papers。
- `/papers` 原页面不受影响。

### 13.2 技术验收

- `frontend/src/app/page.tsx` 不再 import：
  - `DashboardHomePage`
  - `StudioShell`
  - `getFrontendSurface`
- `frontend/src/app/page-content.tsx` 删除。
- `npm run lint` 通过。
- `npm run build` 通过。
- 无明显 hydration error。

### 13.3 体验验收

- 首页第一屏明确表达前台产品。
- 不出现后台监控语义。
- UI 与 `/papers` 风格一致。
- 移动端可读，不溢出。

---

## 14. 实施任务拆分

### Task 1：替换首页

文件：

```text
frontend/src/app/page.tsx
```

动作：

- 删除旧 import。
- 引入 `getPublishedPapers`。
- 写新首页布局。
- 接入 latest papers。

### Task 2：删除旧包装文件

文件：

```text
frontend/src/app/page-content.tsx
```

动作：

- 删除文件。
- 搜索是否仍有引用。

### Task 3：补齐模块入口

文件：

```text
frontend/src/app/page.tsx
```

动作：

- 写 `modules` 配置。
- 写模块卡片区。
- 写 research entries。
- 写 latest papers 区。

### Task 4：导航更新

文件：

```text
frontend/src/config/navigation.ts
```

动作：

- Papers 下改成 Trending Papers / Tasks / Methods。
- 保留 Today / Trends / Reports。
- 移除旧后台概念入口。

### Task 5：测试

命令：

```bash
cd frontend
npm run lint
npm run build
```

---

## 15. 风险

| 风险 | 说明 | 处理 |
|---|---|---|
| 删除过猛 | 直接删 dashboard 可能影响测试或 studio | 分两阶段删 |
| 路由未实现 | `/tech/repos`、`/topics` 可能还是占位 | 首页先提供入口，后续模块补页面 |
| 数据不全 | 只有 papers 有真实数据 | 先静态卡片，后续接 BFF |
| UI 不统一 | 首页和 `/papers` 风格割裂 | 复用 `/papers` 色彩、卡片、间距 |

---

## 16. 不做事项

- 不做后台迁移。
- 不做旧后台样式修复。
- 不做权限系统。
- 不做复杂个性化。
- 不做全量数据接入。
- 不做 dashboard 指标墙。
