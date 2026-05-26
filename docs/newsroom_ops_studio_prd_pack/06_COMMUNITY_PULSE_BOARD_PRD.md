# PRD-06：Community Pulse Board 前台模块

版本：v1.0  
优先级：P1  
建议路由：`/news?source=community` 或 `/community`  
模块定位：社区讨论、开发者反馈和传播信号观察  
状态：已实现（v1 前台）

---

## 1. 背景

很多 AI 技术趋势不会先出现在正式新闻中，而是先出现在社区讨论中，例如：

- Hacker News 热帖
- Reddit 讨论
- GitHub issue / discussion
- 项目 README 被大量传播
- 论文在社区引发争议
- 开发者对某个模型/API 的真实反馈

Community Pulse 用于捕捉这些非正式但非常重要的信号。

---

## 2. 产品定位

Community Pulse 是 NewsRoom 的社区信号观察模块。

一句话：

> 观察社区讨论、开发者反馈、争议热点、传播路径与真实采用信号。

---

## 3. 用户需求

| 用户 | 需求 |
|---|---|
| 开发者 | 看真实使用反馈，而不是官方宣传 |
| Agent 开发者 | 看其他开发者如何评价 agent 框架和工具 |
| 产品人员 | 判断某个产品能力是否被认可 |
| 投资/战略人员 | 发现早期趋势和争议 |
| 内容编辑 | 找到可写成观点文章的社区议题 |

---

## 4. 核心场景

### 4.1 热议主题发现

用户进入 Community Pulse，看到今日社区最热讨论。

### 4.2 开发者反馈查看

用户查看某个项目或产品的社区反馈：

- 好评
- 差评
- 常见问题
- 使用场景
- 替代方案

### 4.3 争议追踪

用户查看某个主题是否存在争议：

- 模型能力是否被质疑
- benchmark 是否被质疑
- 项目是否存在 license 问题
- 产品是否被开发者吐槽

### 4.4 社区信号关联

用户看到社区信号后，可以跳转：

- 相关论文
- 相关项目
- 相关新闻
- 相关主题图谱

---

## 5. 页面结构

```text
/community 或 /news?source=community
├── Hero
│   ├── Community Pulse
│   ├── 今日信号数量
│   └── 热度摘要
├── Filter Bar
│   ├── Source
│   ├── Topic
│   ├── Sentiment
│   ├── Period
│   └── Search
├── Layout
│   ├── Sidebar
│   │   ├── Sources
│   │   ├── Topics
│   │   └── Sentiment
│   └── Signal Stream
│       ├── Hot Discussion Card
│       ├── Signal Row
│       └── Debate Cluster
└── Detail Drawer
```

---

## 6. 来源范围

### 6.1 P0 来源

| 来源 | 说明 |
|---|---|
| Hacker News | 技术社区早期讨论 |
| Reddit | 用户讨论、争议、经验分享 |
| GitHub | issue、discussion、PR、stars |
| GitHub Trending | 项目传播信号 |

### 6.2 P1 来源

| 来源 | 说明 |
|---|---|
| X / Twitter | 社交传播信号 |
| Discord | 项目社区讨论 |
| YouTube | 技术视频反馈 |
| Blogs | 个人博客和技术评论 |

---

## 7. 数据模型

### 7.1 CommunitySignal

```ts
export type CommunitySignal = {
  id: string
  source: CommunitySource
  title: string
  url: string
  author?: string
  summary: string
  postedAt: string
  collectedAt: string
  score?: number
  comments?: number
  sentiment: CommunitySentiment
  topics: string[]
  entities: CommunityEntity[]
  heatScore: number
  controversyScore: number
  adoptionScore: number
  relatedPaperIds: string[]
  relatedProjectIds: string[]
  relatedNewsIds: string[]
}
```

### 7.2 CommunitySource

```ts
export type CommunitySource =
  | "hackernews"
  | "reddit"
  | "github"
  | "github_trending"
  | "x"
  | "blog"
  | "other"
```

### 7.3 CommunitySentiment

```ts
export type CommunitySentiment =
  | "positive"
  | "neutral"
  | "negative"
  | "mixed"
  | "controversial"
```

### 7.4 DebateCluster

```ts
export type DebateCluster = {
  id: string
  title: string
  summary: string
  signalIds: string[]
  topicIds: string[]
  positiveArguments: string[]
  negativeArguments: string[]
  neutralFacts: string[]
  controversyScore: number
  lastUpdatedAt: string
}
```

---

## 8. API 设计

### 8.1 信号列表

```http
GET /api/community/signals
```

Query：

| 参数 | 类型 | 说明 |
|---|---|---|
| source | string | 来源 |
| topic | string | 主题 |
| sentiment | string | 情绪 |
| period | daily / weekly / monthly / all | 时间 |
| sort | hot / newest / controversial / adoption | 排序 |
| q | string | 搜索 |
| limit | number | 数量 |
| cursor | string | 分页 |

Response：

```json
{
  "items": [],
  "clusters": [],
  "facets": {
    "sources": [],
    "topics": [],
    "sentiments": []
  },
  "nextCursor": null
}
```

### 8.2 信号详情

```http
GET /api/community/signals/:id
```

Response：

```json
{
  "signal": {},
  "relatedPapers": [],
  "relatedProjects": [],
  "relatedNews": [],
  "evidenceLinks": []
}
```

---

## 9. 排序规则

### 9.1 Hot

```text
heatScore =
  normalizedScore * 0.35 +
  commentVelocity * 0.25 +
  freshnessScore * 0.20 +
  crossSourceMention * 0.20
```

### 9.2 Controversial

```text
controversyScore =
  argumentSplitScore * 0.35 +
  commentCountScore * 0.25 +
  negativeSignalScore * 0.20 +
  crossCommunitySpread * 0.20
```

### 9.3 Adoption

```text
adoptionScore =
  usageReportCount * 0.30 +
  githubActivityRelated * 0.25 +
  positiveDeveloperFeedback * 0.25 +
  repeatedMentions * 0.20
```

---

## 10. UI 设计

### 10.1 Signal Row

显示：

- 标题
- 来源
- 发布时间
- score/comments
- sentiment
- summary
- topics
- related project/paper/news 数量

### 10.2 Hot Discussion Card

显示：

- 热议标题
- 热度值
- 为什么火
- 主要观点
- 相关链接

### 10.3 Debate Cluster

显示：

```text
议题：某 Agent 框架是否适合生产环境
├── 支持观点
├── 反对观点
├── 中性事实
└── 相关项目 / 论文 / 新闻
```

---

## 11. 与其他模块关系

| 模块 | 关系 |
|---|---|
| AI News | 社区信号可补充新闻背景 |
| Project Radar | 项目社区反馈是采用信号 |
| Paper Radar | 论文社区讨论是影响力信号 |
| Evidence Graph | 社区信号是 evidence node |
| Reports | 热议社区主题可进入报告 |

---

## 12. 首页入口要求

首页必须有 Community Pulse 模块卡片。

标题：

```text
Community Pulse
```

入口：

```text
/community
```

兼容入口：`/news?source=community` 会重定向到 `/community`，并保留可映射筛选参数。

文案：

```text
观察社区讨论、开发者反馈、争议热点、传播路径与真实采用信号。
```

---

## 13. 验收标准

### 13.1 功能验收

- 首页可以看到 Community Pulse。
- 点击进入社区信号页面或带筛选的 news 页面。
- 能展示信号列表或空态。
- 支持 source/topic/sentiment 基础筛选。
- 每条信号有来源、热度、摘要。
- 空数据时不崩溃。

### 13.2 体验验收

- 页面是前台阅读体验，不是后台日志。
- 能快速看出“社区在讨论什么”。
- 热议和争议信号有明显区分。
- 与 `/papers` 风格一致。

### 13.3 技术验收

- 类型定义清晰。
- API 错误可降级。
- 构建通过。
- 运行时基于后端或本地 `community_pulse-productized-board` artifact，不使用 mock 数据。

---

## 14. MVP 切片

第一版：

1. 首页卡片。
2. 社区信号列表页面或 news community 筛选页。
3. 后端 artifact 优先、本地 `.newsroom/runs` artifact 兜底的数据读取。
4. source/topic/sentiment UI。
5. 空态。

后续：

1. HN/Reddit/GitHub 实时数据。
2. 情绪分析。
3. 争议聚类。
4. 项目/论文/新闻关联。
5. Evidence Graph 接入。

---

## 15. 不做事项

- 不做社交平台登录。
- 不做评论回复。
- 不做社区内容发布。
- 不做舆情危机系统。
- 不做后台采集监控。
