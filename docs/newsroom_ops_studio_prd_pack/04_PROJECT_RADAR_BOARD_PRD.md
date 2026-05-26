# PRD-04：Project Radar Board 前台模块

版本：v1.0  
优先级：P0  
路由：`/tech/repos`  
模块定位：开源项目和工程实践雷达  
状态：已实现（已对齐）

---

## 1. 背景

AI 技术的发展不仅体现在论文和新闻中，也体现在开源项目、工程实践和 GitHub 生态中。

大量重要技术趋势会先出现在：

- 新 GitHub 仓库
- Star 快速增长项目
- 论文代码实现
- Agent 框架
- RAG 工具链
- 推理加速工具
- Evaluation 框架
- 开源模型工具

因此需要一个 Project Radar Board，用于把开源项目作为前台内容模块展示。

---

## 2. 产品定位

Project Radar 是 NewsRoom 的开源项目发现与技术采用观察模块。

一句话：

> 追踪 AI 开源项目的出现、增长、采用、关联论文和社区反馈，帮助用户判断哪些技术真正开始被使用。

---

## 3. 目标用户

| 用户 | 需求 |
|---|---|
| AI 工程师 | 找到可用项目、实现方案、工具链 |
| Agent 开发者 | 发现 agent runtime、memory、tool calling、workflow 项目 |
| 技术负责人 | 判断技术栈是否成熟 |
| 研究者 | 查找论文代码实现 |
| 分析师 | 观察开源趋势和采用信号 |

---

## 4. 核心场景

### 4.1 发现热门项目

用户进入 `/tech/repos`，看到近期增长最快的 AI 开源项目。

### 4.2 按技术主题浏览

用户选择：

- Agent
- RAG
- LLM Infra
- Inference
- Evaluation
- Dataset
- Multimodal
- Coding Agent

### 4.3 查看项目详情

项目详情展示：

- 项目描述
- Star 数
- Star 增长
- Fork 数
- Issue 活跃度
- 最近更新
- 技术标签
- 相关论文
- 相关新闻
- 社区讨论

### 4.4 判断技术采用趋势

用户想知道某个技术是不是“开始火了”，Project Radar 要展示：

- Star velocity
- 多社区讨论数量
- 被新闻提及次数
- 是否有论文背书
- 是否有企业采用迹象

---

## 5. 页面结构

```text
/tech/repos
├── Hero
│   ├── Project Radar
│   ├── 项目总数
│   └── 今日新增/增长最快
├── Filter Bar
│   ├── Period
│   ├── Topic
│   ├── Language
│   ├── Sort
│   └── Search
├── Layout
│   ├── Sidebar
│   │   ├── Topics
│   │   ├── Languages
│   │   ├── Licenses
│   │   └── Maturity
│   └── Project Stream
│       ├── Trending Project Card
│       ├── Project Row
│       └── Repository Cluster
└── Project Detail Drawer
```

---

## 6. 项目分类

### 6.1 技术分类

| 分类 | 示例 |
|---|---|
| Agent Framework | agent runtime、workflow、tool calling |
| RAG | retrieval、vector DB、document QA |
| LLM Infra | serving、routing、observability |
| Inference | vLLM、TensorRT、KV cache、quantization |
| Evaluation | benchmark、LLM eval、agent eval |
| Coding | code agent、IDE plugin、review bot |
| Multimodal | vision、audio、video |
| Data | dataset、synthetic data、annotation |
| Memory | long-term memory、knowledge graph |
| Workflow | orchestration、scheduler、state machine |

### 6.2 成熟度分类

| 成熟度 | 标准 |
|---|---|
| New | 30 天内新出现 |
| Rising | Star 增长明显 |
| Active | 近期 commit/issue 活跃 |
| Mature | 长期维护且采用稳定 |
| Dormant | 活跃度下降 |
| Experimental | 研究或 demo 性质 |

---

## 7. 数据模型

### 7.1 ProjectItem

```ts
export type ProjectItem = {
  id: string
  owner: string
  name: string
  fullName: string
  repoUrl: string
  description: string
  homepageUrl?: string
  language?: string
  license?: string
  stars: number
  forks: number
  watchers?: number
  openIssues?: number
  createdAt: string
  updatedAt: string
  pushedAt?: string
  topics: string[]
  categories: ProjectCategory[]
  maturity: ProjectMaturity
  scores: ProjectScores
  relatedPaperIds: string[]
  relatedNewsIds: string[]
  relatedCommunitySignalIds: string[]
}
```

### 7.2 ProjectScores

```ts
export type ProjectScores = {
  trendScore: number
  starVelocityScore: number
  freshnessScore: number
  activityScore: number
  adoptionScore: number
  evidenceScore: number
}
```

### 7.3 ProjectCategory

```ts
export type ProjectCategory =
  | "agent_framework"
  | "rag"
  | "llm_infra"
  | "inference"
  | "evaluation"
  | "coding"
  | "multimodal"
  | "data"
  | "memory"
  | "workflow"
```

### 7.4 ProjectMaturity

```ts
export type ProjectMaturity =
  | "new"
  | "rising"
  | "active"
  | "mature"
  | "dormant"
  | "experimental"
```

---

## 8. API 设计

### 8.1 项目列表

```http
GET /api/projects
```

Query：

| 参数 | 类型 | 说明 |
|---|---|---|
| period | daily / weekly / monthly / all | 时间范围 |
| topic | string | 技术主题 |
| language | string | 编程语言 |
| maturity | string | 成熟度 |
| sort | trending / newest / stars / activity | 排序 |
| q | string | 搜索 |
| limit | number | 数量 |
| cursor | string | 分页 |

Response：

```json
{
  "items": [],
  "facets": {
    "topics": [],
    "languages": [],
    "maturity": []
  },
  "nextCursor": null
}
```

### 8.2 项目详情

```http
GET /api/projects/:id
```

Response：

```json
{
  "project": {},
  "starHistory": [],
  "relatedPapers": [],
  "relatedNews": [],
  "communitySignals": [],
  "timeline": []
}
```

---

## 9. 排序规则

### 9.1 Trending 排序

```text
trendScore =
  starVelocityScore * 0.35 +
  activityScore * 0.20 +
  freshnessScore * 0.15 +
  communityScore * 0.15 +
  evidenceScore * 0.15
```

### 9.2 Activity 排序

```text
activityScore =
  recentCommits * 0.35 +
  issueActivity * 0.25 +
  releaseFreshness * 0.20 +
  contributorGrowth * 0.20
```

### 9.3 Evidence 排序

```text
evidenceScore =
  relatedPaperCount * 0.30 +
  relatedNewsCount * 0.25 +
  communityMentionCount * 0.25 +
  adoptionSignalCount * 0.20
```

---

## 10. UI 设计

### 10.1 Project Row

每个项目显示：

- repo name
- owner
- description
- language
- stars
- star delta
- last updated
- topics
- maturity
- related paper/news/community 数量

### 10.2 Trending Project Card

重点项目卡片显示：

- 大标题
- 增长指标
- 为什么值得关注
- 相关证据
- CTA：Open repo / View detail

### 10.3 Project Detail Drawer

详情抽屉显示：

- 基本信息
- 趋势曲线
- 技术标签
- 相关论文
- 相关新闻
- 社区讨论
- 证据链入口

---

## 11. 与其他模块关系

| 模块 | 关系 |
|---|---|
| Paper Radar | 项目可能是论文代码实现 |
| AI News | 项目可能被新闻提及 |
| Community Pulse | 项目可能被社区讨论 |
| Evidence Graph | 项目是 evidence node |
| Reports | 项目可进入周报或专题 |

---

## 12. 首页入口要求

在 `/` 首页中，Project Radar 卡片必须出现。

卡片标题：

```text
Project Radar
```

入口：

```text
/tech/repos
```

文案：

```text
追踪 GitHub 项目、开源实现、工程实践、增长趋势与技术采用。
```

---

## 13. 验收标准

### 13.1 功能验收

- `/tech/repos` 可访问。
- 首页能跳转到 `/tech/repos`。
- 项目列表能展示。
- 支持搜索。
- 支持 topic 筛选。
- 支持 sort 切换。
- 项目卡片包含 star、language、updatedAt。
- 空数据时有空态。

### 13.2 体验验收

- 不像后台项目表。
- 像前台技术发现页。
- 信息密度高但不拥挤。
- 与 `/papers` 风格一致。

### 13.3 技术验收

- 页面构建通过。
- API 失败不崩溃。
- 运行时使用真实 backend/artifact 数据；无数据时显示明确空态。
- 类型定义清晰。

---

## 14. MVP 切片

第一版：

1. `/tech/repos` 页面。
2. 真实 backend/artifact 项目数据；无数据时显示空态。
3. Project Card。
4. topic/filter/sort UI。
5. 首页入口。

后续：

1. GitHub live enrichment 和 Star 历史增强。
2. Star 历史曲线。
3. 论文关联。
4. 社区提及。
5. Evidence Graph 关联。

---

## 15. 不做事项

- 不做 GitHub OAuth。
- 不做仓库写操作。
- 不做 issue 管理。
- 不做后台采集监控。
- 不做复杂图谱可视化。
