# PRD-03：AI News Board 前台模块

版本：v1.0  
优先级：P0  
路由：`/news`  
模块定位：新闻与行业动态前台板块  
状态：已实现（已对齐）

---

## 1. 背景

NewsRoom 的前台不能只展示论文。AI 技术生态每天都有大量新闻信号，包括：

- 官方博客更新
- 产品发布
- 模型能力更新
- 融资并购
- 公司战略
- 开源发布
- 政策监管
- 生态合作

这些信息应该组成一个独立的 AI News Board，作为前台重要模块。

---

## 2. 产品定位

AI News Board 是 NewsRoom 面向用户的 AI 行业动态入口。

它不是后台采集监控页，而是一个新闻阅读、筛选、聚合和趋势理解页面。

一句话：

> 帮助用户快速了解 AI 行业、产品、公司、生态和政策层面的关键变化。

---

## 3. 用户需求

| 用户 | 需求 |
|---|---|
| 开发者 | 了解新模型、新 API、新工具、新框架 |
| 产品经理 | 了解 AI 产品变化和竞品动态 |
| 投资/战略人员 | 了解融资、并购、公司动态 |
| 研究者 | 判断某个研究方向是否开始产业化 |
| 编辑/分析师 | 找到值得写日报/周报的新闻主题 |

---

## 4. 核心场景

### 4.1 今日新闻浏览

用户打开 `/news`，看到今日重要新闻，按重要性排序。

### 4.2 按来源筛选

用户选择：

- Official Updates
- Product Updates
- Funding
- Policy
- Community
- Open Source

### 4.3 按主题筛选

用户选择：

- Agents
- LLMs
- Multimodal
- Coding Agents
- RAG
- AI Infra
- Robotics
- Evaluation
- Safety

### 4.4 新闻详情阅读

用户点击新闻，进入详情页或打开侧边抽屉，查看：

- 标题
- 摘要
- 来源
- 原文链接
- 相关论文
- 相关项目
- 相关社区讨论
- 时间线
- 可信度/证据

---

## 5. 页面结构

```text
/news
├── Hero
│   ├── AI News 标题
│   ├── 今日新闻数量
│   └── 来源覆盖范围
├── Filter Bar
│   ├── Period: Today / Week / Month / All
│   ├── Source Type
│   ├── Topic
│   └── Sort
├── Main Layout
│   ├── Left Sidebar
│   │   ├── Topics
│   │   ├── Source Types
│   │   └── Companies
│   └── News Stream
│       ├── Top Story Card
│       ├── News Row
│       └── Cluster Card
└── Detail Drawer
```

---

## 6. 信息架构

### 6.1 一级分类

| 分类 | 说明 |
|---|---|
| Top Stories | 当日最重要新闻 |
| Official Updates | 官方博客、release notes、公告 |
| Product Updates | 产品、API、平台能力变化 |
| Open Source | 开源项目发布或更新 |
| Funding & M&A | 融资、收购、投资 |
| Policy & Ecosystem | 政策、监管、生态合作 |
| Community Buzz | 社区热议新闻 |

### 6.2 二级主题

| 主题 | 示例 |
|---|---|
| Agents | Agent 框架、工具调用、工作流 |
| LLMs | 大模型发布、推理能力、API |
| Multimodal | 图像、视频、语音、多模态 |
| Coding | 编程助手、代码生成、IDE Agent |
| Infra | 推理框架、Serving、GPU、向量数据库 |
| Evaluation | Benchmark、评测框架、安全评测 |
| Research | 论文产业化、研究突破 |
| Enterprise | 企业应用、SaaS、生产部署 |

---

## 7. 数据模型

### 7.1 NewsItem

```ts
export type NewsItem = {
  id: string
  title: string
  summary: string
  sourceName: string
  sourceUrl: string
  originalUrl: string
  publishedAt: string
  collectedAt: string
  language: "zh" | "en" | "other"
  category: NewsCategory
  topics: string[]
  entities: NewsEntity[]
  importanceScore: number
  freshnessScore: number
  credibilityScore: number
  trendScore: number
  relatedPaperIds: string[]
  relatedProjectIds: string[]
  relatedCommunitySignalIds: string[]
}
```

### 7.2 NewsCategory

```ts
export type NewsCategory =
  | "official_update"
  | "product_update"
  | "funding"
  | "mna"
  | "policy"
  | "ecosystem"
  | "open_source"
  | "community"
  | "research"
```

### 7.3 NewsEntity

```ts
export type NewsEntity = {
  type: "company" | "product" | "model" | "person" | "paper" | "project" | "topic"
  name: string
  canonicalId?: string
}
```

### 7.4 NewsCluster

```ts
export type NewsCluster = {
  id: string
  title: string
  summary: string
  itemIds: string[]
  primaryItemId: string
  topics: string[]
  firstSeenAt: string
  lastUpdatedAt: string
  heatScore: number
}
```

---

## 8. API 设计

### 8.1 新闻列表

```http
GET /api/news
```

Query：

| 参数 | 类型 | 说明 |
|---|---|---|
| period | `daily` / `weekly` / `monthly` / `all` | 时间范围 |
| category | string | 新闻类型 |
| topic | string | 主题 |
| source | string | 来源 |
| q | string | 搜索关键词 |
| sort | `top` / `newest` / `trending` | 排序 |
| limit | number | 数量 |
| cursor | string | 分页 |

Response：

```json
{
  "items": [],
  "clusters": [],
  "nextCursor": null,
  "facets": {
    "topics": [],
    "categories": [],
    "sources": []
  }
}
```

### 8.2 新闻详情

```http
GET /api/news/:id
```

Response：

```json
{
  "item": {},
  "relatedPapers": [],
  "relatedProjects": [],
  "relatedCommunitySignals": [],
  "timeline": []
}
```

---

## 9. 排序规则

### 9.1 Top 排序

```text
topScore =
  importanceScore * 0.35 +
  freshnessScore * 0.25 +
  credibilityScore * 0.20 +
  trendScore * 0.20
```

### 9.2 Newest 排序

按 `publishedAt` 倒序。

### 9.3 Trending 排序

```text
trendingScore =
  velocityScore * 0.40 +
  crossSourceCount * 0.25 +
  communityMentions * 0.20 +
  relatedProjectGrowth * 0.15
```

---

## 10. UI 设计要求

### 10.1 News Row

每条新闻显示：

- 标题
- 摘要
- 来源
- 发布时间
- 分类标签
- 主题标签
- 关联数量：
  - related papers
  - related projects
  - community mentions

### 10.2 Top Story Card

Top Story 应比普通 row 更突出：

- 大标题
- 摘要
- 关键证据
- 来源数量
- 更新时间
- CTA：Read brief

### 10.3 Cluster Card

当多个来源报道同一事件时展示 cluster：

```text
OpenAI 发布新模型能力更新
├── Official blog
├── Hacker News discussion
├── GitHub related repo
└── 相关论文 3 篇
```

---

## 11. 状态设计

| 状态 | UI |
|---|---|
| loading | skeleton news rows |
| empty | 显示“暂无新闻，调整筛选条件” |
| error | 显示错误提示和重试按钮 |
| partial | 显示已有缓存，并提示部分来源不可用 |
| ready | 正常新闻流 |

---

## 12. 与其他模块关系

| 模块 | 关系 |
|---|---|
| Paper Radar | 新闻可关联论文 |
| Project Radar | 新闻可关联开源项目 |
| Community Pulse | 新闻可关联讨论热度 |
| Evidence Graph | 新闻是证据节点 |
| Reports | 新闻可进入日报/周报 |

---

## 13. 验收标准

### 13.1 功能验收

- `/news` 可访问。
- 可展示新闻列表。
- 支持 period 筛选。
- 支持 category 筛选。
- 支持 topic 筛选。
- 支持搜索。
- 新闻卡片有来源和发布时间。
- 点击新闻可进入详情或打开详情抽屉。
- 相关新闻、项目、社区信号可展示为空态或真实数据。

### 13.2 体验验收

- 页面风格与 `/papers` 一致。
- 新闻页不像后台表格。
- 重点信息在第一屏可见。
- 标签和筛选不拥挤。
- 移动端可读。

### 13.3 技术验收

- `npm run lint` 通过。
- `npm run build` 通过。
- API 失败时页面不崩溃。
- 空数据时有明确空态。

---

## 14. MVP 切片

第一版只做：

1. `/news` 页面。
2. 真实 backend/artifact 新闻数据；无真实数据时显示明确空态。
3. 新闻卡片列表。
4. period/category/topic 筛选 UI。
5. 首页入口跳转。

不做：

- 复杂聚类。
- 自动摘要。
- 实时推送。
- 个性化推荐。
- 登录订阅。

---

## 15. 后续增强

- 新闻聚类。
- 事件时间线。
- 多源证据合并。
- 与论文和项目自动关联。
- 日报/周报自动生成入口。
- 用户关注主题。
