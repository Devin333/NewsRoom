# PRD-05：Paper Radar Board 前台模块

版本：v1.0
优先级：P0
路由：`/papers`、`/papers/tasks`、`/papers/methods`
模块定位：论文、任务、方法和研究前沿发现
状态：已实现（已对齐）

---

## 1. 背景

`/papers` 当前已经形成新的前台 UI 方向，因此 Paper Radar 不只是一个普通页面，而是整个前台 UI 的母版。

用户明确要求：

- 前台根据 `/papers` 的 UI 来设计。
- 旧后台删除。
- 前台模块中要写上论文模块。
- Paper 模块需要包括之前扩展出来的几个入口。

因此 Paper Radar 的一级入口应收敛为：

1. Trending Papers
2. Tasks
3. Methods

---

## 2. 产品定位

Paper Radar 是 NewsRoom 的研究前沿发现模块。

一句话：

> 以论文为起点，组织任务、方法、代码实现、benchmark 和跨板块证据，帮助用户理解 AI 技术演进。

---

## 3. 页面范围

| 页面 | 路由 | 说明 |
|---|---|---|
| Trending Papers | `/papers` | 趋势论文列表 |
| Tasks | `/papers/tasks` | 按研究任务组织论文 |
| Methods | `/papers/methods` | 按技术方法组织论文 |
| Paper Detail | `/papers?paper=:id` 或详情抽屉 | 论文详情 |
| Task Detail | `/papers/tasks/:slug` | 任务详情 |
| Method Detail | `/papers/methods/:slug` | 方法详情 |

---

## 4. 当前页面能力

已有页面链路：

```text
frontend/src/app/papers/page.tsx
frontend/src/app/papers/papers-page-client.tsx
frontend/src/components/papers/trending-papers-page.tsx
```

已有能力包括：

- 从 `getPublishedPapers()` 获取论文。
- `PapersPageClient` 读取 locale。
- `TrendingPapersPage` 展示论文列表。
- 支持 period。
- 支持 sort。
- 支持 search。
- 支持 paper detail drawer。
- 支持 domain sidebar。

当前实现已补齐：

- `/api/papers` 支持 `q`、`period`、`sort`、`task`、`method`、`limit`、`offset`，并在 backend 不可用时使用真实 cache/artifact 数据。
- `/api/papers/tasks`、`/api/papers/methods` 可在 backend 不可用时使用本地 taxonomy，但 counts、latest papers、implementations 只从真实 paper 数据派生。
- 运行时不再把 bundled catalog papers 当作前台业务论文流；没有 backend/cache/artifact 数据时展示 empty/degraded 状态。
- Paper detail drawer 已展示 implementations、benchmarks、news/source、community、evidence refs；缺失时显示空态。

---

## 5. 核心目标

### 5.1 P0 目标

- 保持 `/papers` 页面稳定。
- 在首页和导航中明确写上：
  - Trending Papers
  - Tasks
  - Methods
- 保持 UI 作为前台母版。
- 首页 latest papers 接入真实 paper 数据。

### 5.2 P1 目标

- Tasks 页面支持任务列表。
- Methods 页面支持方法列表。
- Task/Method 详情页展示相关论文、项目和 benchmark。
- 论文详情展示相关项目、新闻和社区讨论。

### 5.3 P2 目标

- 支持论文阅读器。
- 支持笔记。
- 支持论文问答。
- 支持论文证据链。
- 支持 researcher watchlist。

---

## 6. 信息架构

### 6.1 Trending Papers

展示：

- 趋势论文
- 最新论文
- 高引用论文
- 有代码论文
- 热门任务论文

筛选：

- Daily
- Weekly
- Monthly
- All
- Search
- Sort

排序：

- Trending
- Newest
- Most Cited

### 6.2 Tasks

任务维度组织论文：

| Task | 示例 |
|---|---|
| Agent Planning | agent planning、task decomposition |
| Tool Use | function calling、tool learning |
| RAG | retrieval augmented generation |
| Long Context | context compression、memory |
| Multimodal Reasoning | image/video reasoning |
| Code Generation | coding agent、program repair |
| Evaluation | benchmark、eval methodology |

每个 Task 展示：

- task name
- description
- paper count
- top methods
- latest papers
- related projects
- benchmark status

### 6.3 Methods

方法维度组织论文：

| Method | 示例 |
|---|---|
| Chain-of-Thought | 推理链 |
| ReAct | reasoning + acting |
| Toolformer | tool-use learning |
| RAG | retrieval 增强 |
| Memory-Augmented Agent | 长短期记忆 |
| Graph-of-Thought | 图推理 |
| Self-Reflection | 自我反思 |
| Agentic Workflow | 多步骤执行 |

每个 Method 展示：

- method name
- description
- origin paper
- representative papers
- related tasks
- related projects
- strengths / limitations

---

## 7. 数据模型

### 7.1 Paper

```ts
export type Paper = {
  id: string
  slug: string
  title: string
  summary: string
  authors: string[]
  publishedAt: string
  updatedAt?: string
  source: "arxiv" | "openreview" | "papers_with_code" | "other"
  url: string
  pdfUrl?: string
  repoUrl?: string
  tasks: string[]
  methods: string[]
  domains: string[]
  tags: string[]
  citations?: number
  scores: PaperScores
}
```

### 7.2 PaperScores

```ts
export type PaperScores = {
  trending: number
  freshness: number
  citation: number
  implementation: number
  community: number
}
```

### 7.3 PaperTask

```ts
export type PaperTask = {
  id: string
  slug: string
  name: string
  description: string
  paperCount: number
  methodCount: number
  benchmarkCount: number
  topPaperIds: string[]
  trendingMethodIds: string[]
}
```

### 7.4 PaperMethod

```ts
export type PaperMethod = {
  id: string
  slug: string
  name: string
  description: string
  originPaperId?: string
  representativePaperIds: string[]
  relatedTaskIds: string[]
  relatedProjectIds: string[]
  strengths: string[]
  limitations: string[]
}
```

---

## 8. API 设计

### 8.1 Papers

```http
GET /api/papers
```

Query：

| 参数 | 类型 | 说明 |
|---|---|---|
| q | string | 搜索 |
| period | daily / weekly / monthly / all | 时间 |
| sort | trending / newest / most_cited | 排序 |
| task | string | 任务 |
| method | string | 方法 |
| limit | number | 数量 |

### 8.2 Tasks

```http
GET /api/papers/tasks
```

Response：

```json
{
  "tasks": []
}
```

### 8.3 Methods

```http
GET /api/papers/methods
```

Response：

```json
{
  "methods": []
}
```

### 8.4 Paper Detail

```http
GET /api/papers/:paperId
```

Response：

```json
{
  "paper": {},
  "relatedProjects": [],
  "relatedNews": [],
  "communitySignals": [],
  "evidenceLinks": []
}
```

---

## 9. 首页展示要求

首页必须写上 Paper Radar。

### 9.1 模块卡片

标题：

```text
Paper Radar
```

入口：

```text
/papers
```

文案：

```text
聚合论文、任务、方法、代码实现与研究前沿变化。
```

### 9.2 Research Entries

首页 Research Module 必须展示：

```text
Trending Papers -> /papers
Tasks -> /papers/tasks
Methods -> /papers/methods
```

### 9.3 Latest Papers

首页展示 latest papers：

- 标题
- 摘要
- 点击进入 `/papers?paper=:id`

---

## 10. UI 设计

### 10.1 Papers UI 原则

Paper 页面是整个前台母版：

- editorial hero
- period tabs
- search bar
- domain sidebar
- stream list
- detail drawer
- light card
- subtle border
- 高信息密度

### 10.2 Task 页面

Task 页面可采用：

```text
Task Hero
Task Stats
Task Grid
Task Detail Preview
Related Methods
Latest Papers by Task
```

### 10.3 Method 页面

Method 页面可采用：

```text
Method Hero
Method Families
Method Cards
Origin Paper
Representative Papers
Related Projects
```

---

## 11. 与其他模块关系

| 模块 | 关系 |
|---|---|
| AI News | 新闻可引用论文 |
| Project Radar | 项目可实现论文 |
| Community Pulse | 论文可被社区讨论 |
| Evidence Graph | 论文是证据链核心节点 |
| Reports | 论文可进入日报/周报 |

---

## 12. 验收标准

### 12.1 功能验收

- `/papers` 正常显示。
- `/papers/tasks` 正常显示或有清晰占位。
- `/papers/methods` 正常显示或有清晰占位。
- 首页可进入三个入口。
- 导航 Papers 下只有 Trending Papers / Tasks / Methods。
- latest papers 使用真实数据。
- paper drawer 能正常打开。

### 12.2 体验验收

- `/papers` 视觉不被破坏。
- 首页与 `/papers` 风格一致。
- 论文模块不是后台风格。
- 搜索和筛选清晰。

### 12.3 技术验收

- `npm run lint` 通过。
- `npm run build` 通过。
- API 错误有真实 backend/cache/artifact fallback；没有真实数据时显示 empty/degraded state。
- 数据为空有 empty state。

---

## 13. 实施任务

### Task 1：首页接入 latest papers

文件：

```text
frontend/src/app/page.tsx
```

### Task 2：导航收敛

文件：

```text
frontend/src/config/navigation.ts
```

Papers 子项改为：

```ts
[
  { label: "Trending Papers", href: "/papers" },
  { label: "Tasks", href: "/papers/tasks" },
  { label: "Methods", href: "/papers/methods" }
]
```

### Task 3：确认 tasks/methods 页面

检查：

```text
frontend/src/app/papers/tasks/page.tsx
frontend/src/app/papers/methods/page.tsx
```

如果不存在，则创建基础页面。

---

## 14. 不做事项

- 不把 Paper 页面改成后台表格。
- 不删除现有 `/papers` 真实数据链路。
- 不在本轮实现复杂论文问答。
- 不做付费阅读功能。
- 不做外部账号登录。
