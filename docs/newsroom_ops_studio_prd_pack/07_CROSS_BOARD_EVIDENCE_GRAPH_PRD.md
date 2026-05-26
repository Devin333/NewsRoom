# PRD-07：Cross-board Evidence Graph 跨板块证据图谱

版本：v1.0
优先级：P1
建议路由：`/topics?view=evidence-graph`
模块定位：连接新闻、论文、项目和社区信号的证据链
状态：已实现（前台 v1）

---

## 1. 背景

NewsRoom 不应该只是把新闻、论文、项目、社区讨论分开展示。真正有价值的是把这些信号串起来，回答：

- 一个技术趋势从哪里开始？
- 哪些论文支撑了它？
- 哪些项目实现了它？
- 社区是否认可？
- 新闻是否报道？
- 它是在升温还是退潮？
- 证据是否可靠？

因此需要 Cross-board Evidence Graph。

---

## 2. 产品定位

Cross-board Evidence Graph 是 NewsRoom 的跨模块知识组织和证据推理层。

一句话：

> 把 Paper、Project、Community、AI News 串成证据链和技术演进链。

---

## 3. 核心价值

| 价值 | 说明 |
|---|---|
| 统一证据 | 不再孤立看新闻、论文、项目 |
| 趋势解释 | 解释为什么一个主题正在升温 |
| 可信判断 | 多源交叉验证，降低单一来源偏差 |
| 技术演化 | 展示技术从论文到实现再到采用的路径 |
| 报告生成 | 为日报、周报、专题提供结构化证据 |

---

## 4. 核心场景

### 4.1 查看主题证据链

用户搜索或点击主题：

```text
Agent Memory
```

页面展示：

```text
Agent Memory
├── 相关论文
├── 相关项目
├── 相关新闻
├── 社区讨论
├── 时间线
└── 趋势判断
```

### 4.2 判断某个趋势是否真实

用户看到某个主题很热，想知道它是否只是噪声。

系统展示：

- 论文数量是否增长
- 项目是否增长
- 社区是否持续讨论
- 新闻是否多源报道
- 是否有真实采用信号

### 4.3 生成报告证据

分析师写报告时，可以直接从 evidence graph 拿到：

- 关键证据
- 事件顺序
- 相关实体
- 支持/反对信号
- 可信度评分

---

## 5. 页面结构

```text
/topics?view=evidence-graph
├── Hero
│   ├── Evidence Graph
│   ├── 搜索主题
│   └── 当前图谱规模
├── Topic Search / Selector
├── Graph Summary
│   ├── Trend Score
│   ├── Evidence Score
│   ├── Confidence
│   └── Signal Mix
├── Evidence Layout
│   ├── Left: Topic / Entity Sidebar
│   ├── Center: Graph / Timeline
│   └── Right: Evidence Inspector
└── Related Reports
```

---

## 6. 图谱节点

### 6.1 Node 类型

```ts
export type EvidenceNodeType =
  | "topic"
  | "paper"
  | "project"
  | "news"
  | "community_signal"
  | "company"
  | "model"
  | "method"
  | "task"
  | "report"
```

### 6.2 EvidenceNode

```ts
export type EvidenceNode = {
  id: string
  type: EvidenceNodeType
  title: string
  summary?: string
  url?: string
  source?: string
  createdAt?: string
  updatedAt?: string
  score?: number
  confidence?: number
  tags?: string[]
  metadata?: Record<string, unknown>
}
```

---

## 7. 图谱边

### 7.1 Edge 类型

```ts
export type EvidenceEdgeType =
  | "mentions"
  | "implements"
  | "cites"
  | "discusses"
  | "supports"
  | "contradicts"
  | "derived_from"
  | "same_topic"
  | "released_by"
  | "reported_by"
```

### 7.2 EvidenceEdge

```ts
export type EvidenceEdge = {
  id: string
  sourceNodeId: string
  targetNodeId: string
  type: EvidenceEdgeType
  confidence: number
  evidenceText?: string
  createdAt?: string
  metadata?: Record<string, unknown>
}
```

---

## 8. Topic Evidence Summary

```ts
export type TopicEvidenceSummary = {
  topicId: string
  topicName: string
  summary: string
  trendScore: number
  evidenceScore: number
  confidenceScore: number
  paperCount: number
  projectCount: number
  newsCount: number
  communitySignalCount: number
  firstSeenAt: string
  lastUpdatedAt: string
  trajectory: "rising" | "stable" | "declining" | "noisy" | "uncertain"
  keyEvidenceNodeIds: string[]
}
```

---

## 9. API 设计

### 9.1 获取主题证据图

```http
GET /api/evidence-graph
```

Query：

| 参数 | 类型 | 说明 |
|---|---|---|
| topic | string | 主题 |
| entity | string | 实体 |
| period | daily / weekly / monthly / all | 时间范围 |
| nodeTypes | string | 节点类型 |
| depth | number | 图谱深度 |
| limit | number | 节点数量限制 |

Response：

```json
{
  "summary": {},
  "nodes": [],
  "edges": [],
  "timeline": [],
  "relatedReports": []
}
```

### 9.2 获取节点详情

```http
GET /api/evidence-graph/nodes/:id
```

Response：

```json
{
  "node": {},
  "incomingEdges": [],
  "outgoingEdges": [],
  "relatedNodes": []
}
```

### 9.3 获取主题时间线

```http
GET /api/topics/:topicId/timeline
```

Response：

```json
{
  "items": []
}
```

---

## 10. 评分规则

### 10.1 Evidence Score

```text
evidenceScore =
  sourceDiversityScore * 0.30 +
  nodeCountScore * 0.20 +
  confidenceAverage * 0.20 +
  recencyScore * 0.15 +
  crossBoardCoverage * 0.15
```

### 10.2 Trend Score

```text
trendScore =
  newsVelocity * 0.25 +
  paperVelocity * 0.20 +
  projectVelocity * 0.25 +
  communityVelocity * 0.20 +
  reportMention * 0.10
```

### 10.3 Confidence Score

```text
confidenceScore =
  verifiedSourceRatio * 0.35 +
  crossSourceAgreement * 0.25 +
  sourceReliability * 0.25 +
  contradictionPenalty * -0.15
```

---

## 11. UI 设计

### 11.1 Graph Summary Card

显示：

- topic name
- summary
- trend score
- evidence score
- confidence
- signal mix

Signal Mix 示例：

```text
Papers 24
Projects 8
News 16
Community 42
```

### 11.2 Timeline

按时间展示：

```text
2025-11：关键论文出现
2026-01：GitHub 项目快速增长
2026-02：社区讨论升温
2026-03：官方产品能力发布
```

### 11.3 Evidence Inspector

点击节点后显示：

- 节点标题
- 类型
- 摘要
- 来源
- 相关边
- 可信度
- 原文链接

---

## 12. 首页入口要求

首页必须展示 Cross-board Evidence Graph 模块卡片。

标题：

```text
Cross-board Evidence Graph
```

入口：

```text
/topics?view=evidence-graph
```

文案：

```text
把 Paper、Project、Community、AI News 串成证据链和技术演进链。
```

---

## 13. 与其他模块关系

| 模块 | 节点类型 |
|---|---|
| AI News | news |
| Project Radar | project |
| Paper Radar | paper / task / method |
| Community Pulse | community_signal |
| Reports | report |
| Topics | topic |

---

## 14. MVP 切片

第一版不一定做复杂可视化，可以先做结构化证据链页面：

1. topic 搜索框。
2. topic summary。
3. 四列证据：
   - Papers
   - Projects
   - News
   - Community
4. timeline。
5. related reports。

后续再做图可视化。

---

## 15. 验收标准

### 15.1 功能验收

- `/topics?view=evidence-graph` 可访问。
- 首页可以跳转到该页面。
- 可以展示主题证据摘要。
- 可以看到 paper/project/news/community 四类证据。
- 可以看到时间线。
- 空数据时不崩溃。

### 15.2 体验验收

- 用户能理解“这个趋势为什么重要”。
- 不只是普通列表。
- 多源证据关系清楚。
- 与前台 UI 风格一致。

### 15.3 技术验收

- 类型定义清晰。
- API 可 mock。
- 构建通过。
- 未来可替换为真实图谱数据。

---

## 16. 不做事项

- 第一版不强制做复杂力导向图。
- 不做实时图数据库查询。
- 不做大型知识图谱编辑器。
- 不做后台标注工具。
- 不做人工审核队列。

---

## 17. 实现说明

- 前台入口：`/topics?view=evidence-graph`。
- API：`/api/evidence-graph`、`/api/evidence-graph/nodes/:id`、`/api/topics/:topicId/timeline`。
- v1 使用现有真实数据加载器聚合 Paper Radar、Project Radar、AI News、Community Pulse 和 Reports，不使用 bundled mock 数据作为证据来源。
- v1 采用结构化证据链、时间线和 Inspector，不实现复杂力导向图或实时图数据库查询。
