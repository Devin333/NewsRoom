import type { Evidence } from "@/types/evidence";
import type { NewsItem } from "@/types/news";
import type { Report } from "@/types/report";
import type { SearchResult } from "@/types/search";
import type { TechItem } from "@/types/tech";
import type { Topic, TopicTimelineItem } from "@/types/topic";
import type { Artifact } from "@/types/artifact";
import type { MemoryItem } from "@/types/memory";
import type { QualityCheck, QualityResult } from "@/types/quality";
import type { Source } from "@/types/source";

const topicSeeds = [
  {
    id: "ai-coding-agent-competition",
    name: "AI 编码 Agent 竞争",
    category: "开发者工具",
    trend: "rising" as const,
    entities: ["OpenAI", "Anthropic", "Cursor", "SWE-bench"],
    tags: ["编码 Agent", "开发者工具", "基准测试"],
  },
  {
    id: "agent-runtime-observability",
    name: "Agent 运行时可观测性",
    category: "Agent 运行时",
    trend: "rising" as const,
    entities: ["LangSmith", "OpenTelemetry", "CrewAI", "LangGraph"],
    tags: ["可观测性", "追踪", "运行时"],
  },
  {
    id: "multimodal-foundation-models",
    name: "多模态基础模型",
    category: "模型",
    trend: "stable" as const,
    entities: ["Gemini", "GPT-4o", "Claude", "Qwen-VL"],
    tags: ["多模态", "视觉", "音频"],
  },
  {
    id: "open-source-llm-tooling",
    name: "开源 LLM 工具链",
    category: "开源",
    trend: "stable" as const,
    entities: ["Ollama", "vLLM", "llama.cpp", "Hugging Face"],
    tags: ["开源", "工具链", "本地 LLM"],
  },
  {
    id: "ai-browser-and-web-agent",
    name: "AI 浏览器与 Web Agent",
    category: "效率工具",
    trend: "rising" as const,
    entities: ["Browserbase", "Playwright", "Perplexity", "OpenAI"],
    tags: ["浏览器 Agent", "Web 自动化", "效率"],
  },
  {
    id: "inference-infrastructure",
    name: "推理基础设施",
    category: "基础设施",
    trend: "stable" as const,
    entities: ["NVIDIA", "Groq", "Together AI", "Fireworks"],
    tags: ["推理", "GPU", "服务化"],
  },
  {
    id: "rag-evaluation",
    name: "RAG 评估",
    category: "评估",
    trend: "rising" as const,
    entities: ["RAGAS", "LlamaIndex", "DeepEval", "Arize"],
    tags: ["RAG", "评估", "检索"],
  },
  {
    id: "workflow-orchestration",
    name: "工作流编排",
    category: "工作流",
    trend: "falling" as const,
    entities: ["Temporal", "Dagster", "Prefect", "LangGraph"],
    tags: ["工作流", "编排", "持久化"],
  },
];

function trendLabel(trend: (typeof topicSeeds)[number]["trend"]) {
  if (trend === "rising") return "上升";
  if (trend === "falling") return "回落";
  return "稳定";
}

export const evidences: Evidence[] = Array.from({ length: 18 }, (_, index) => {
  const seed = topicSeeds[index % topicSeeds.length];
  const sourceCycle = [
    ["OpenAI Blog", "official_blog"],
    ["arXiv", "arxiv"],
    ["GitHub Trending", "github"],
    ["Hacker News", "hackernews"],
    ["The Information", "media"],
    ["Reddit LocalLLaMA", "reddit"],
  ] as const;
  const [sourceName, sourceType] = sourceCycle[index % sourceCycle.length];
  return {
    id: `ev-${String(index + 1).padStart(2, "0")}`,
    title: `${seed.name} 信号 ${index + 1}`,
    sourceName,
    sourceType,
    capturedAt: `2026-05-${String(3 + index).padStart(2, "0")}T10:30:00Z`,
    summary: `证据显示 ${seed.name} 仍在持续升温，相关信号包括新发布、基准讨论和工程团队采用。`,
    quote: index % 3 === 0 ? `公开讨论将 ${seed.entities[0]} 视为 ${seed.category} 采用趋势的参考点。` : undefined,
    credibility: index % 5 === 0 ? "medium" : "high",
    confidenceScore: 72 + (index % 7) * 4,
    relationReason: `匹配实体 ${seed.entities.slice(0, 2).join("、")} 以及标签 ${seed.tags.slice(0, 2).join("、")}。`,
    originalUrl: `https://example.com/newsroom/evidence/${index + 1}`,
  };
});

function analysisFieldsFor(seed: (typeof topicSeeds)[number], index: number, variant: "release" | "community"): Pick<NewsItem, "detailedSummary" | "whyItMatters" | "status" | "keyFacts" | "agentExplanation"> {
  const primaryEvidenceId = `ev-${String(index + (variant === "release" ? 1 : 2)).padStart(2, "0")}`;
  const sourceName = variant === "release" ? "官方工程博客" : index % 2 === 0 ? "GitHub Trending" : "Hacker News";
  const status = variant === "release" ? "reported" : index % 3 === 0 ? "needs_review" : "clustered";

  return {
    detailedSummary:
      variant === "release"
        ? `${seed.name} 正从单点发布变成可衡量的平台信号。NewsRoom 将发布内容与高频实体、证据质量和后续讨论关联起来，帮助运营者区分长期采用与发布周期噪声。`
        : `${seed.name} 周边的社区活动显示团队正在真实试验的方向。这个信号弱于官方发布，但仓库变化和讨论速度仍适合用于早期趋势识别。`,
    whyItMatters:
      variant === "release"
        ? `这条新闻会影响工程团队评估 ${seed.category} 路线图，因为它同时包含一手来源、可见采用和可比较证据。`
        : `这条新闻是需求侧指标：社区反复讨论往往比官方叙事更早暴露实践摩擦。`,
    status,
    keyFacts: [
      {
        id: `${seed.id}-${variant}-fact-1`,
        text: `${seed.name} 归入 ${seed.category} 分类，当前主题轨迹为${trendLabel(seed.trend)}。`,
        sourceName,
        confidence: variant === "release" ? "high" : "medium",
        evidenceId: primaryEvidenceId,
      },
      {
        id: `${seed.id}-${variant}-fact-2`,
        text: `最强实体重叠包括 ${seed.entities.slice(0, 2).join(" 和 ")}。`,
        sourceName: "NewsRoom 实体匹配器",
        confidence: "high",
        evidenceId: primaryEvidenceId,
      },
      {
        id: `${seed.id}-${variant}-fact-3`,
        text: `标签 ${seed.tags.slice(0, 2).join(" 和 ")} 将该条目连接到相邻的读者工作流。`,
        sourceName: "TopicClusterAgent",
        confidence: variant === "release" ? "high" : "medium",
      },
    ],
    agentExplanation: [
      `公开证据将该条目关联到 ${seed.name} 主题簇。`,
      `来源可信度、证据新鲜度和实体重叠支撑当前热度分。`,
      variant === "release"
        ? "该条目具备一手来源上下文和关联证据，可纳入报告候选。"
        : "该条目可作为采用信号继续使用，同时保留社区来源风险供复核。",
    ],
  };
}

export const newsItems: NewsItem[] = topicSeeds.flatMap((seed, index) => [
  {
    id: `news-${index + 1}-a`,
    title: `${seed.name}：新发布压力重塑本周判断`,
    summary: `${seed.name} 的一组最新更新，正在改变团队比较能力、可靠性和生产就绪度的方式。`,
    sourceName: index % 2 === 0 ? "官方工程博客" : "AI 基础设施周报",
    sourceType: index % 2 === 0 ? "official_blog" : "rss",
    sourceUrl: `https://example.com/news/${seed.id}/release`,
    publishedAt: `2026-05-${String(10 + index).padStart(2, "0")}T08:00:00Z`,
    collectedAt: `2026-05-${String(10 + index).padStart(2, "0")}T08:12:00Z`,
    category: seed.category,
    tags: seed.tags,
    heatScore: 70 + index * 3,
    qualityScore: 82 + (index % 4) * 3,
    credibility: "high",
    topicId: seed.id,
    topicName: seed.name,
    reportIds: index < 4 ? ["report-daily-ai-runtime"] : undefined,
    evidenceIds: [`ev-${String(index + 1).padStart(2, "0")}`, `ev-${String(index + 9).padStart(2, "0")}`],
    ...analysisFieldsFor(seed, index, "release"),
  },
  {
    id: `news-${index + 1}-b`,
    title: `${seed.name} 的社区采用记录`,
    summary: `开发者论坛和仓库活动显示，${seed.name} 正在哪些方向从实验进入团队工作流。`,
    sourceName: index % 2 === 0 ? "GitHub Trending" : "Hacker News",
    sourceType: index % 2 === 0 ? "github" : "hackernews",
    sourceUrl: `https://example.com/news/${seed.id}/community`,
    publishedAt: `2026-05-${String(12 + index).padStart(2, "0")}T12:00:00Z`,
    collectedAt: `2026-05-${String(12 + index).padStart(2, "0")}T12:10:00Z`,
    category: seed.category,
    tags: [...seed.tags, "社区"],
    heatScore: 62 + index * 3,
    qualityScore: 76 + (index % 4) * 3,
    credibility: index % 3 === 0 ? "medium" : "high",
    topicId: seed.id,
    topicName: seed.name,
    evidenceIds: [`ev-${String(index + 2).padStart(2, "0")}`],
    ...analysisFieldsFor(seed, index, "community"),
  },
]);

function timelineFor(seed: (typeof topicSeeds)[number], seedIndex: number): TopicTimelineItem[] {
  return [
    {
      id: `${seed.id}-tl-1`,
      topicId: seed.id,
      occurredAt: `2026-05-${String(3 + seedIndex).padStart(2, "0")}T09:00:00Z`,
      title: "检测到初始信号簇",
      summary: `多个来源开始以重叠实体和共同术语引用 ${seed.name}。`,
      sourceCount: 3 + (seedIndex % 3),
      evidenceIds: [`ev-${String(seedIndex + 1).padStart(2, "0")}`],
      importance: "medium",
      type: "media",
      relatedNewsId: `news-${seedIndex + 1}-a`,
    },
    {
      id: `${seed.id}-tl-2`,
      topicId: seed.id,
      occurredAt: `2026-05-${String(8 + seedIndex).padStart(2, "0")}T14:00:00Z`,
      title: "实践采用信号增强",
      summary: `仓库、演示和工程文章开始将 ${seed.entities[0]} 作为实践决策的参考基准。`,
      sourceCount: 5 + (seedIndex % 4),
      evidenceIds: [`ev-${String(seedIndex + 2).padStart(2, "0")}`, `ev-${String(seedIndex + 10).padStart(2, "0")}`],
      importance: seed.trend === "rising" ? "high" : "medium",
      type: seed.category === "开源" ? "repo" : "community",
      relatedNewsId: `news-${seedIndex + 1}-b`,
    },
    {
      id: `${seed.id}-tl-3`,
      topicId: seed.id,
      occurredAt: `2026-05-${String(16 + seedIndex).padStart(2, "0")}T16:30:00Z`,
      title: "Agent 分析更新轨迹",
      summary: `TrendHunterAgent 根据来源多样性、引用质量和相关技术引用更新了主题轨迹。`,
      sourceCount: 4 + (seedIndex % 5),
      evidenceIds: [`ev-${String(seedIndex + 3).padStart(2, "0")}`],
      importance: seed.trend === "falling" ? "low" : "high",
      type: "agent",
    },
  ];
}

export const techItems: TechItem[] = [
  {
    id: "tech-swe-bench-agent-harness",
    name: "SWE-bench Agent 评测套件",
    type: "framework",
    summary: "用于比较编码 Agent 在仓库级问题修复能力上的可重复评测套件。",
    problem: "团队需要可比较的 Agent 评估，而不是依赖零散演示。",
    maturity: "emerging",
    sourceUrl: "https://example.com/tech/swe-bench-agent-harness",
    relatedTopicIds: ["ai-coding-agent-competition"],
    relatedTopicNames: ["AI 编码 Agent 竞争"],
    tags: ["基准测试", "编码 Agent"],
    agentEvaluation: "对选择 Agent 编码工作流的产品团队有较高参考价值。",
    referenceValue: "可作为 Agent 回归测试基线。",
  },
  {
    id: "tech-otel-agent-spans",
    name: "OpenTelemetry Agent Span",
    type: "method",
    summary: "面向 Agent 步骤、工具调用、记忆读取和门控决策的追踪约定。",
    maturity: "experimental",
    sourceUrl: "https://example.com/tech/otel-agent-spans",
    relatedTopicIds: ["agent-runtime-observability"],
    relatedTopicNames: ["Agent 运行时可观测性"],
    tags: ["可观测性", "追踪"],
    agentEvaluation: "方向有潜力，但跨框架标准化仍不足。",
    referenceValue: "可作为内部 trace schema 的术语参考。",
  },
  {
    id: "tech-vllm-prefix-cache",
    name: "vLLM 前缀缓存调优",
    type: "practice",
    summary: "用于降低推理集群重复上下文预填成本的运行调优模式。",
    maturity: "stable",
    sourceUrl: "https://example.com/tech/vllm-prefix-cache",
    relatedTopicIds: ["inference-infrastructure"],
    relatedTopicNames: ["推理基础设施"],
    tags: ["推理", "成本"],
    agentEvaluation: "适合存在重复提示模式的团队进入生产使用。",
    referenceValue: "可纳入高吞吐服务检查清单。",
  },
  {
    id: "tech-ragas-claim-eval",
    name: "RAGAS 声明级评估",
    type: "framework",
    summary: "用于评分答案依据、上下文精度和检索质量的评估工具。",
    maturity: "stable",
    sourceUrl: "https://example.com/tech/ragas",
    relatedTopicIds: ["rag-evaluation"],
    relatedTopicNames: ["RAG 评估"],
    tags: ["RAG", "评估"],
    agentEvaluation: "非常适合夜间回归评测套件。",
    referenceValue: "可用于检索质量仪表盘。",
  },
  {
    id: "tech-browser-agent-sandbox",
    name: "浏览器 Agent 沙箱",
    type: "repo",
    summary: "用于受控 Web Agent 运行的浏览器自动化沙箱，支持会话回放。",
    maturity: "emerging",
    sourceUrl: "https://example.com/tech/browser-agent-sandbox",
    relatedTopicIds: ["ai-browser-and-web-agent"],
    relatedTopicNames: ["AI 浏览器与 Web Agent"],
    tags: ["浏览器 Agent", "沙箱"],
    agentEvaluation: "当 Web Agent 从演示转向可持久工作流时值得持续跟踪。",
    referenceValue: "可作为安全浏览器任务执行模式。",
  },
  {
    id: "tech-multimodal-routing-paper",
    name: "按不确定性路由多模态请求",
    type: "paper",
    summary: "一篇提出按不确定性和成本边界路由图像、文本、音频请求的论文。",
    maturity: "experimental",
    sourceUrl: "https://example.com/tech/multimodal-routing",
    relatedTopicIds: ["multimodal-foundation-models"],
    relatedTopicNames: ["多模态基础模型"],
    tags: ["多模态", "路由"],
    agentEvaluation: "仍处研究阶段，但与成本敏感的模型编排直接相关。",
    referenceValue: "适合用于架构评审。",
  },
  {
    id: "tech-ollama-enterprise-patterns",
    name: "Ollama 企业部署模式",
    type: "practice",
    summary: "面向内部网关和策略控制之后的本地 LLM 运行时部署指南。",
    maturity: "stable",
    sourceUrl: "https://example.com/tech/ollama-enterprise",
    relatedTopicIds: ["open-source-llm-tooling"],
    relatedTopicNames: ["开源 LLM 工具链"],
    tags: ["本地 LLM", "治理"],
    agentEvaluation: "对试点本地推理的受监管团队很实用。",
    referenceValue: "可作为参考架构采用。",
  },
  {
    id: "tech-langgraph-durable-flows",
    name: "LangGraph 持久化流程",
    type: "framework",
    summary: "基于图的 Agent 编排，具备可恢复状态和显式控制流。",
    maturity: "emerging",
    sourceUrl: "https://example.com/tech/langgraph-durable-flows",
    relatedTopicIds: ["workflow-orchestration", "agent-runtime-observability"],
    relatedTopicNames: ["工作流编排", "Agent 运行时可观测性"],
    tags: ["工作流", "Agent 运行时"],
    agentEvaluation: "适合需要检查的 Agent 工作流建模。",
    referenceValue: "可与基于 Temporal 的设计对比。",
  },
  {
    id: "tech-groq-latency-profile",
    name: "Groq 延迟画像",
    type: "repo",
    summary: "一个公开基准仓库，用于比较短轮次 Agent 的低延迟推理路径。",
    maturity: "emerging",
    sourceUrl: "https://example.com/tech/groq-latency-profile",
    relatedTopicIds: ["inference-infrastructure"],
    relatedTopicNames: ["推理基础设施"],
    tags: ["延迟", "推理"],
    agentEvaluation: "有助于规划快速响应型 Agent 用户体验。",
    referenceValue: "可作为延迟预算参考。",
  },
  {
    id: "tech-retrieval-failure-taxonomy",
    name: "检索失败分类法",
    type: "paper",
    summary: "覆盖上下文遗漏、证据过期、引用漂移和无支撑综合的失败分类法。",
    maturity: "stable",
    sourceUrl: "https://example.com/tech/retrieval-failure-taxonomy",
    relatedTopicIds: ["rag-evaluation"],
    relatedTopicNames: ["RAG 评估"],
    tags: ["检索", "质量"],
    agentEvaluation: "对报告质量门控很有价值。",
    referenceValue: "可用于分类失败的证据检查。",
  },
  {
    id: "tech-playwright-agent-controls",
    name: "Playwright Agent 控制层",
    type: "framework",
    summary: "用于限制浏览器 Agent 导航、动作预算和数据暴露的控制原语。",
    maturity: "emerging",
    sourceUrl: "https://example.com/tech/playwright-agent-controls",
    relatedTopicIds: ["ai-browser-and-web-agent"],
    relatedTopicNames: ["AI 浏览器与 Web Agent"],
    tags: ["浏览器 Agent", "安全"],
    agentEvaluation: "可作为浏览器自动化的安全层。",
    referenceValue: "适合用于沙箱策略设计。",
  },
  {
    id: "tech-open-weights-eval-suite",
    name: "开放权重评估套件",
    type: "repo",
    summary: "社区评估套件，用于比较开放权重模型在编码、检索和工具使用任务上的表现。",
    maturity: "stable",
    sourceUrl: "https://example.com/tech/open-weights-eval-suite",
    relatedTopicIds: ["open-source-llm-tooling"],
    relatedTopicNames: ["开源 LLM 工具链"],
    tags: ["开源", "评估"],
    agentEvaluation: "对本地模型选型有较强参考价值。",
    referenceValue: "可纳入每周工具链评审。",
  },
];

export const topics: Topic[] = topicSeeds.map((seed, index) => ({
  id: seed.id,
  name: seed.name,
  summary: `${seed.name} 正作为 ${seed.category} 趋势被跟踪，信号来自产品发布、开发者讨论和证据质量变化。`,
  executiveSummary: `NewsRoom 将 ${seed.name} 识别为${seed.trend === "rising" ? "加速上升" : seed.trend === "falling" ? "热度回落" : "稳定延展"}的主题。最强证据来自来源多样性、命名实体重复出现以及工程团队的实践采用。`,
  trend: seed.trend,
  heatScore: 78 + (index % 5) * 4 - (seed.trend === "falling" ? 12 : 0),
  qualityScore: 82 + (index % 4) * 3,
  itemCount: 18 + index * 3,
  sourceCount: 5 + (index % 4),
  firstSeenAt: `2026-04-${String(18 + index).padStart(2, "0")}T08:00:00Z`,
  lastSeenAt: `2026-05-${String(19 + index).padStart(2, "0")}T18:00:00Z`,
  category: seed.category,
  entities: seed.entities,
  tags: seed.tags,
  timeline: timelineFor(seed, index),
  sourceCoverage: [
    {
      sourceName: "官方工程博客",
      sourceType: "official_blog",
      itemCount: 3 + index,
      firstSeenAt: `2026-04-${String(19 + index).padStart(2, "0")}T08:00:00Z`,
      lastSeenAt: `2026-05-${String(19 + index).padStart(2, "0")}T10:00:00Z`,
      credibility: "high",
      coverageSummary: "一手发布与技术上下文。",
    },
    {
      sourceName: "GitHub Trending",
      sourceType: "github",
      itemCount: 4 + (index % 3),
      firstSeenAt: `2026-05-${String(4 + index).padStart(2, "0")}T09:00:00Z`,
      lastSeenAt: `2026-05-${String(18 + index).padStart(2, "0")}T12:00:00Z`,
      credibility: "medium",
      coverageSummary: "仓库活动与实践案例。",
    },
    {
      sourceName: "AI 基础设施周报",
      sourceType: "rss",
      itemCount: 2 + (index % 4),
      firstSeenAt: `2026-05-${String(6 + index).padStart(2, "0")}T13:00:00Z`,
      lastSeenAt: `2026-05-${String(20 + index).padStart(2, "0")}T16:00:00Z`,
      credibility: "high",
      coverageSummary: "精选分析与生态对比。",
    },
  ],
  evidenceIds: [`ev-${String(index + 1).padStart(2, "0")}`, `ev-${String(index + 2).padStart(2, "0")}`, `ev-${String(index + 10).padStart(2, "0")}`],
  relatedNewsIds: [`news-${index + 1}-a`, `news-${index + 1}-b`],
  relatedTechItemIds: techItems.filter((item) => item.relatedTopicIds?.includes(seed.id)).map((item) => item.id),
  agentAnalysis: [
    {
      agent: "HistorianAgent",
      summary: `该主题可追溯到此前的 ${seed.category} 周期：可信发布后出现可见的社区复现，随后进入采用阶段。`,
    },
    {
      agent: "AnalystAgent",
      summary: `当前轨迹为${trendLabel(seed.trend)}；最强驱动因素是独立来源中反复出现的实体重叠。`,
    },
    {
      agent: "WriterAgent",
      summary: `报告叙事应强调它为什么影响工程团队，而不只复述公告流。`,
    },
    {
      agent: "ReviewerAgent",
      summary: "质量可接受，但仍需注意社区来源重复和基准选择性引用风险。",
    },
    {
      agent: "TrendHunterAgent",
      summary: seed.trend === "falling" ? "继续观察，但降低刷新频率。" : "继续每日跟踪，并补充仓库级证据。",
    },
  ],
  trendHistory: Array.from({ length: 7 }, (_, point) => ({
    date: `5月${10 + point}日`,
    heatScore: 58 + point * (seed.trend === "rising" ? 5 : seed.trend === "falling" ? -2 : 2) + index,
    itemCount: 8 + point + index,
  })),
  qualityGate: {
    status: index % 6 === 0 ? "review" : "passed",
    summary: index % 6 === 0 ? "来源重叠需要人工复核。" : "证据覆盖和引用质量足以支持发布。",
    checks: ["来源多样性满足要求", "未发现无支撑声明", "Agent 摘要不包含私有推理"],
  },
}));

export const reports: Report[] = [
  {
    id: "report-daily-ai-runtime",
    title: "每日 AI 运行时情报简报",
    reportType: "daily",
    generatedAt: "2026-05-22T07:30:00Z",
    coveredFrom: "2026-05-21T00:00:00Z",
    coveredTo: "2026-05-22T00:00:00Z",
    agentName: "WriterAgent",
    qualityScore: 91,
    topicIds: ["agent-runtime-observability", "ai-coding-agent-competition", "rag-evaluation"],
    newsItemIds: ["news-1-a", "news-2-a", "news-7-a"],
    evidenceIds: ["ev-01", "ev-02", "ev-07", "ev-12"],
    status: "published",
    markdown: `# 每日 AI 运行时情报简报

## 执行摘要

Agent 运行时工具正在从框架公告，转向证据丰富的运营实践。最强信号包括 trace 标准化、编码 Agent 基准压力，以及 RAG 评估逐渐成为发布就绪的一部分。

## 关键发现

- [x] Agent 可观测性讨论已经覆盖步骤结果、工具 trace、记忆读取和门控决策。
- [x] 编码 Agent 竞争正在从演示质量转向可重复的仓库级评估。
- [ ] 浏览器 Agent 安全控制在生态中仍不均衡。

## 来源矩阵

| 主题 | 来源多样性 | 证据质量 | 方向 |
|---|---:|---:|---|
| Agent 运行时可观测性 | 7 | 91% | 上升 |
| AI 编码 Agent 竞争 | 6 | 88% | 上升 |
| RAG 评估 | 5 | 86% | 上升 |

## 为什么重要

采用 Agent 的团队需要运行后可检查的运行时证据。没有可追踪结果，质量门控就容易变成主观判断，并且难以复现。

> 建议：在扩展自主行为之前，优先建立可观测的运行时 trace。

## 工程备注

\`\`\`ts
type RuntimeEvidence = {
  traceId: string
  stepOutcomes: string[]
  gateResult: "passed" | "review" | "failed"
}
\`\`\`

## 外部参考

- [OpenTelemetry](https://opentelemetry.io/)
- [SWE-bench](https://www.swebench.com/)

---

由 NewsRoom WriterAgent 生成。`,
  },
  {
    id: "report-weekly-tech-radar",
    title: "每周技术雷达：Agent 基础设施",
    reportType: "tech",
    generatedAt: "2026-05-21T08:00:00Z",
    coveredFrom: "2026-05-14T00:00:00Z",
    coveredTo: "2026-05-21T00:00:00Z",
    agentName: "TrendHunterAgent",
    qualityScore: 88,
    topicIds: ["inference-infrastructure", "open-source-llm-tooling", "workflow-orchestration"],
    newsItemIds: ["news-4-a", "news-6-a", "news-8-a"],
    evidenceIds: ["ev-04", "ev-06", "ev-08"],
    status: "reviewed",
    markdown: "# 每周技术雷达：Agent 基础设施\n\n推理服务和工作流编排仍是本周价值最高的基础设施类别。",
  },
  {
    id: "report-topic-rag-evaluation",
    title: "主题深潜：RAG 评估",
    reportType: "topic",
    generatedAt: "2026-05-20T15:15:00Z",
    coveredFrom: "2026-05-01T00:00:00Z",
    coveredTo: "2026-05-20T00:00:00Z",
    agentName: "AnalystAgent",
    qualityScore: 89,
    topicIds: ["rag-evaluation"],
    newsItemIds: ["news-7-a", "news-7-b"],
    evidenceIds: ["ev-07", "ev-15"],
    status: "published",
    markdown: "# 主题深潜：RAG 评估\n\nRAG 评估正在成为证据支撑型 AI 产品的标准质量循环。",
  },
  {
    id: "report-source-health-ai",
    title: "来源健康报告：AI 技术来源",
    reportType: "source_health",
    generatedAt: "2026-05-19T09:10:00Z",
    coveredFrom: "2026-05-12T00:00:00Z",
    coveredTo: "2026-05-19T00:00:00Z",
    agentName: "ReviewerAgent",
    qualityScore: 84,
    topicIds: ["multimodal-foundation-models", "open-source-llm-tooling"],
    newsItemIds: ["news-3-a", "news-4-b"],
    evidenceIds: ["ev-03", "ev-04"],
    status: "generated",
    markdown: "# 来源健康报告\n\n官方博客和精选 RSS 仍是本跟踪窗口内最可靠的来源。",
  },
  {
    id: "report-quality-gate-weekly",
    title: "每周质量门控摘要",
    reportType: "quality",
    generatedAt: "2026-05-18T11:45:00Z",
    coveredFrom: "2026-05-11T00:00:00Z",
    coveredTo: "2026-05-18T00:00:00Z",
    agentName: "ReviewerAgent",
    qualityScore: 86,
    topicIds: ["ai-browser-and-web-agent", "workflow-orchestration"],
    newsItemIds: ["news-5-a", "news-8-b"],
    evidenceIds: ["ev-05", "ev-08"],
    status: "reviewed",
    markdown: "# 每周质量门控摘要\n\n大多数生成报告通过了证据覆盖检查；浏览器 Agent 相关声明需要更严格的来源控制。",
  },
  {
    id: "report-weekly-model-systems",
    title: "每周模型系统简报",
    reportType: "weekly",
    generatedAt: "2026-05-17T08:30:00Z",
    coveredFrom: "2026-05-10T00:00:00Z",
    coveredTo: "2026-05-17T00:00:00Z",
    agentName: "WriterAgent",
    qualityScore: 87,
    topicIds: ["multimodal-foundation-models", "inference-infrastructure"],
    newsItemIds: ["news-3-a", "news-6-b"],
    evidenceIds: ["ev-06", "ev-09"],
    status: "published",
    markdown: "# 每周模型系统简报\n\n多模态系统和推理基础设施正围绕低延迟产品工作流趋于融合。",
  },
];

export const additionalSearchResults: SearchResult[] = [
  {
    id: "memory-runtime-evidence",
    objectType: "memory",
    title: "记忆：运行时证据偏好",
    summary: "历史偏好显示，报告应引用 trace ID、来源多样性和门控结果。",
    matchedSnippet: "trace ID、来源多样性和门控结果",
    timestamp: "2026-05-18T10:00:00Z",
    tags: ["memory", "quality"],
    relevanceScore: 78,
    href: "/search?q=runtime",
  },
  {
    id: "source-openai-blog",
    objectType: "source",
    title: "来源：OpenAI Blog",
    summary: "用于模型与产品公告的高可信官方来源。",
    timestamp: "2026-05-20T12:00:00Z",
    tags: ["official_blog"],
    sourceName: "OpenAI Blog",
    relevanceScore: 82,
    href: "/search?q=openai",
  },
  {
    id: "agent-run-daily-522",
    objectType: "agent_run",
    title: "Agent 运行：2026-05-22 每日情报",
    summary: "已完成运行，生成了每日 AI 运行时情报简报。",
    timestamp: "2026-05-22T07:30:00Z",
    tags: ["agent-run", "report"],
    relevanceScore: 74,
    href: "/reports/report-daily-ai-runtime",
  },
];

export const sources: Source[] = [
  {
    id: "openai-blog",
    name: "OpenAI Blog",
    type: "official_blog",
    enabled: true,
    healthStatus: "healthy",
    lastRunAt: "2026-05-22T23:15:00Z",
    lastSuccessAt: "2026-05-22T23:15:12Z",
    errorCount24h: 0,
    collectedCount24h: 18,
    avgLatencyMs: 842,
    configProfile: "官方高可信",
    configSummary: "官方博客来源，启用 HTML 抽取和规范 URL 检查。",
    errorSummary: [],
    recentRuns: [
      { id: "src-run-001", status: "healthy", startedAt: "2026-05-22T23:15:00Z", finishedAt: "2026-05-22T23:15:12Z", collectedCount: 4, latencyMs: 812 },
      { id: "src-run-002", status: "healthy", startedAt: "2026-05-22T17:15:00Z", finishedAt: "2026-05-22T17:15:11Z", collectedCount: 3, latencyMs: 866 },
    ],
    latestItems: [
      { id: "item-openai-1", title: "Agent 安全评估更新", capturedAt: "2026-05-22T23:15:10Z" },
      { id: "item-openai-2", title: "生产级 Agent 的 Realtime API 模式", capturedAt: "2026-05-22T17:15:09Z" },
    ],
  },
  {
    id: "anthropic-blog",
    name: "Anthropic Blog",
    type: "official_blog",
    enabled: true,
    healthStatus: "healthy",
    lastRunAt: "2026-05-22T22:40:00Z",
    lastSuccessAt: "2026-05-22T22:40:09Z",
    errorCount24h: 0,
    collectedCount24h: 11,
    avgLatencyMs: 704,
    configProfile: "官方高可信",
    configSummary: "官方博客来源，启用发布日期校验。",
    recentRuns: [{ id: "src-run-003", status: "healthy", startedAt: "2026-05-22T22:40:00Z", finishedAt: "2026-05-22T22:40:09Z", collectedCount: 2, latencyMs: 704 }],
    latestItems: [{ id: "item-anthropic-1", title: "策略感知编码助手部署笔记", capturedAt: "2026-05-22T22:40:07Z" }],
  },
  {
    id: "deepmind-blog",
    name: "Google DeepMind Blog",
    type: "official_blog",
    enabled: true,
    healthStatus: "degraded",
    lastRunAt: "2026-05-22T21:25:00Z",
    lastSuccessAt: "2026-05-22T15:25:08Z",
    errorCount24h: 2,
    collectedCount24h: 7,
    avgLatencyMs: 1512,
    configProfile: "官方重试",
    errorSummary: ["过去 24 小时出现两次临时 503 响应。", "延迟高于 1.5 秒移动平均线。"],
    configSummary: "官方博客来源，启用重试策略和过期缓存兜底。",
    recentRuns: [
      { id: "src-run-004", status: "degraded", startedAt: "2026-05-22T21:25:00Z", finishedAt: "2026-05-22T21:25:18Z", collectedCount: 1, latencyMs: 1820, errorMessage: "上游临时超时" },
      { id: "src-run-005", status: "healthy", startedAt: "2026-05-22T15:25:00Z", finishedAt: "2026-05-22T15:25:08Z", collectedCount: 2, latencyMs: 1330 },
    ],
    latestItems: [{ id: "item-dm-1", title: "多模态推理基准发布", capturedAt: "2026-05-22T15:25:07Z" }],
  },
  {
    id: "github-trending",
    name: "GitHub Trending",
    type: "github",
    enabled: true,
    healthStatus: "healthy",
    lastRunAt: "2026-05-22T23:00:00Z",
    lastSuccessAt: "2026-05-22T23:00:06Z",
    errorCount24h: 0,
    collectedCount24h: 56,
    avgLatencyMs: 492,
    configProfile: "社区每小时",
    configSummary: "面向 AI、Agent、向量和基础设施主题的仓库趋势采集器。",
    recentRuns: [{ id: "src-run-006", status: "healthy", startedAt: "2026-05-22T23:00:00Z", finishedAt: "2026-05-22T23:00:06Z", collectedCount: 12, latencyMs: 492 }],
    latestItems: [
      { id: "item-gh-1", title: "open-agent-runtime 本周新增 2.4k star", capturedAt: "2026-05-22T23:00:06Z" },
      { id: "item-gh-2", title: "eval-harness-lite 发布确定性 trace 模式", capturedAt: "2026-05-22T22:00:05Z" },
    ],
  },
  {
    id: "hackernews-ai",
    name: "HackerNews",
    type: "hackernews",
    enabled: true,
    healthStatus: "degraded",
    lastRunAt: "2026-05-22T22:55:00Z",
    lastSuccessAt: "2026-05-22T22:55:04Z",
    errorCount24h: 4,
    collectedCount24h: 39,
    avgLatencyMs: 378,
    configProfile: "社区快速",
    errorSummary: ["4 个条目因缺少规范 URL 被跳过。", "1 个讨论页面返回了畸形文本。"],
    configSummary: "面向 AI 基础设施和开发者工具的 HN 讨论采集器。",
    recentRuns: [{ id: "src-run-007", status: "degraded", startedAt: "2026-05-22T22:55:00Z", finishedAt: "2026-05-22T22:55:04Z", collectedCount: 8, latencyMs: 378, errorMessage: "跳过畸形讨论页面" }],
    latestItems: [{ id: "item-hn-1", title: "Show HN：面向 Agent 的确定性工作流 trace", capturedAt: "2026-05-22T22:55:04Z" }],
  },
  {
    id: "reddit-localllama",
    name: "Reddit LocalLLaMA",
    type: "reddit",
    enabled: true,
    healthStatus: "failed",
    lastRunAt: "2026-05-22T20:30:00Z",
    lastSuccessAt: "2026-05-21T20:30:05Z",
    errorCount24h: 9,
    collectedCount24h: 0,
    avgLatencyMs: 2480,
    configProfile: "社区限速",
    errorSummary: ["配置令牌超过速率限制。", "兜底缓存已超过 24 小时。"],
    configSummary: "社区来源，使用保守的速率限制预算。",
    recentRuns: [{ id: "src-run-008", status: "failed", startedAt: "2026-05-22T20:30:00Z", finishedAt: "2026-05-22T20:30:23Z", collectedCount: 0, latencyMs: 2480, errorMessage: "HTTP 429 触发速率限制" }],
    latestItems: [],
  },
  {
    id: "arxiv-cs-ai",
    name: "arXiv cs.AI",
    type: "arxiv",
    enabled: true,
    healthStatus: "healthy",
    lastRunAt: "2026-05-22T19:00:00Z",
    lastSuccessAt: "2026-05-22T19:00:14Z",
    errorCount24h: 1,
    collectedCount24h: 24,
    avgLatencyMs: 1120,
    configProfile: "论文每日",
    errorSummary: ["1 次 PDF 元数据抓取超时后被跳过。"],
    configSummary: "面向 cs.AI 和 cs.CL 论文的每日 arXiv feed 采集器。",
    recentRuns: [{ id: "src-run-009", status: "healthy", startedAt: "2026-05-22T19:00:00Z", finishedAt: "2026-05-22T19:00:14Z", collectedCount: 24, latencyMs: 1120 }],
    latestItems: [{ id: "item-arxiv-1", title: "面向长周期工具使用的 trace-grounded Agent", capturedAt: "2026-05-22T19:00:11Z" }],
  },
  {
    id: "rss-custom-labs",
    name: "RSS 自定义来源",
    type: "rss",
    enabled: false,
    healthStatus: "disabled",
    lastRunAt: "2026-05-20T10:00:00Z",
    lastSuccessAt: "2026-05-20T10:00:05Z",
    errorCount24h: 0,
    collectedCount24h: 0,
    avgLatencyMs: 630,
    configProfile: "自定义暂停",
    configSummary: "自定义 RSS 来源已暂停，等待 feed 归属复核。",
    recentRuns: [{ id: "src-run-010", status: "disabled", startedAt: "2026-05-20T10:00:00Z", finishedAt: "2026-05-20T10:00:05Z", collectedCount: 3, latencyMs: 630 }],
    latestItems: [{ id: "item-rss-1", title: "实验室笔记：生产级 RAG 评估模式", capturedAt: "2026-05-20T10:00:03Z" }],
  },
];

export const memoryItems: MemoryItem[] = [
  memory("mem-news-001", "news", "OpenAI 发布 Agent 安全评估更新", "官方来源更新，关联到更安全的长运行 Agent 部署。", "2026-05-22T23:30:00Z", "high", 94, ["Agent", "安全"], ["OpenAI"], ["agent-runtime-observability"], "official_blog"),
  memory("mem-news-002", "news", "GitHub 趋势显示轻量评测套件增长", "仓库活动表明团队重新关注确定性 Agent 测试。", "2026-05-22T22:40:00Z", "medium", 82, ["GitHub", "评测"], ["GitHub"], ["rag-evaluation"], "github"),
  memory("mem-topic-001", "topic", "Agent 运行时可观测性", "覆盖 trace、工具调用和工作流运行证据的主题簇。", "2026-05-22T21:12:00Z", "high", 91, ["运行时", "trace"], ["LangSmith", "OpenTelemetry"], ["agent-runtime-observability"], "official_blog"),
  memory("mem-topic-002", "topic", "本地模型部署质量", "围绕小型 LLM 部署质量和本地评估循环的主题簇。", "2026-05-22T18:44:00Z", "medium", 77, ["本地 LLM", "质量"], ["LocalLLaMA"], ["open-source-llm-tooling"], "reddit"),
  memory("mem-evidence-001", "evidence", "OpenAI 博客规范文章", "Agent 安全策略更新的一手证据。", "2026-05-22T23:16:00Z", "high", 98, ["一手", "策略"], ["OpenAI"], ["agent-runtime-observability"], "official_blog"),
  memory("mem-evidence-002", "evidence", "Anthropic 策略部署说明", "策略感知编码助手部署的辅助证据。", "2026-05-22T22:42:00Z", "high", 93, ["一手", "编码 Agent"], ["Anthropic"], ["ai-coding-agent-competition"], "official_blog"),
  memory("mem-evidence-003", "evidence", "HN 关于确定性 trace 的讨论", "社区讨论确认开发者对基于 trace 的调试有兴趣。", "2026-05-22T22:58:00Z", "medium", 71, ["社区", "trace"], ["HackerNews"], ["agent-runtime-observability"], "hackernews"),
  memory("mem-evidence-004", "evidence", "arXiv 关于 trace-grounded Agent 的论文", "长周期工具使用评估的论文证据。", "2026-05-22T19:04:00Z", "high", 89, ["论文", "工具使用"], ["arXiv"], ["rag-evaluation"], "arxiv"),
  memory("mem-evidence-005", "evidence", "GitHub 仓库发布说明", "发布说明提到确定性回放模式。", "2026-05-22T20:01:00Z", "medium", 80, ["仓库", "发布"], ["GitHub"], ["workflow-orchestration"], "github"),
  memory("mem-evidence-006", "evidence", "DeepMind 基准公告", "多模态推理趋势的官方基准证据。", "2026-05-22T15:27:00Z", "high", 88, ["基准", "多模态"], ["Google DeepMind"], ["multimodal-foundation-models"], "official_blog"),
  memory("mem-evidence-007", "evidence", "Reddit 速率限制事件记录", "运营证据显示社区来源采集失败。", "2026-05-22T20:35:00Z", "low", 52, ["来源健康", "Reddit"], ["Reddit"], ["open-source-llm-tooling"], "reddit"),
  memory("mem-evidence-008", "evidence", "RSS 暂停来源复核", "自定义来源停用状态的证据。", "2026-05-20T10:04:00Z", "medium", 66, ["RSS", "治理"], ["Custom Labs"], ["workflow-orchestration"], "rss"),
  memory("mem-entity-001", "entity", "OpenAI", "实体画像，近期在 Agent 安全和实时运行时更新中被频繁提及。", "2026-05-22T23:35:00Z", "high", 96, ["实体", "实验室"], ["OpenAI"], ["agent-runtime-observability"], "official_blog"),
  memory("mem-entity-002", "entity", "Anthropic", "实体画像，包含编码 Agent 策略部署上下文。", "2026-05-22T22:50:00Z", "high", 92, ["实体", "实验室"], ["Anthropic"], ["ai-coding-agent-competition"], "official_blog"),
  memory("mem-entity-003", "entity", "Google DeepMind", "实体画像，关联多模态基准覆盖。", "2026-05-22T15:35:00Z", "high", 87, ["实体", "基准"], ["Google DeepMind"], ["multimodal-foundation-models"], "official_blog"),
  memory("mem-entity-004", "entity", "LocalLLaMA", "社区实体，显示本地模型部署讨论和来源健康风险。", "2026-05-22T20:45:00Z", "medium", 69, ["实体", "社区"], ["LocalLLaMA"], ["open-source-llm-tooling"], "reddit"),
  memory("mem-entity-005", "entity", "arXiv cs.AI", "论文来源实体，具备稳定的每日采集模式。", "2026-05-22T19:10:00Z", "high", 84, ["实体", "论文"], ["arXiv"], ["rag-evaluation"], "arxiv"),
  memory("mem-report-001", "report", "每日 AI 基础设施报告", "生成报告，将来源健康与 Agent 运行时趋势关联起来。", "2026-05-22T23:45:00Z", "high", 90, ["报告", "每日"], ["NewsRoom"], ["agent-runtime-observability"], "custom"),
  memory("mem-agent-001", "agent_note", "质量 Agent 标记引用缺口", "Agent 笔记建议为报告章节补充辅助证据。", "2026-05-22T23:50:00Z", "medium", 75, ["Agent 笔记", "质量"], ["ReviewerAgent"], ["rag-evaluation"], "custom"),
  memory("mem-agent-002", "agent_note", "来源健康 Agent 上报 Reddit 失败", "Agent 笔记标记 Reddit LocalLLaMA 需要运营复核。", "2026-05-22T20:40:00Z", "high", 86, ["Agent 笔记", "来源健康"], ["SourceHealthAgent"], ["open-source-llm-tooling"], "custom"),
  memory("mem-agent-003", "agent_note", "主题聚类 Agent 合并运行时 trace", "Agent 笔记记录 trace 与工作流证据簇的合并。", "2026-05-22T21:35:00Z", "medium", 73, ["Agent 笔记", "主题"], ["TopicClusterAgent"], ["agent-runtime-observability"], "custom"),
];

export const qualityResults: QualityResult[] = Array.from({ length: 20 }, (_, index) => {
  const statuses: QualityResult["status"][] = ["passed", "warning", "failed", "review_required"];
  const objectTypes: QualityResult["objectType"][] = ["news", "topic", "report", "run"];
  const status = index < 5 ? "review_required" : index < 8 ? "failed" : statuses[index % statuses.length];
  const objectType = objectTypes[index % objectTypes.length];
  const score = status === "passed" ? 88 + (index % 10) : status === "warning" ? 68 + (index % 10) : status === "review_required" ? 58 + (index % 14) : 31 + (index % 20);
  const checks = makeQualityChecks(index, status);
  return {
    id: `quality-${String(index + 1).padStart(3, "0")}`,
    objectType,
    objectId: `${objectType}-${String(index + 1).padStart(3, "0")}`,
    objectTitle: qualityTitle(index, objectType),
    score,
    status,
    issueCount: checks.filter((check) => check.status !== "passed").length,
    checks,
    createdAt: new Date(Date.UTC(2026, 4, 22, 23 - (index % 18), 10 + index)).toISOString(),
    reviewerDecision: status === "review_required" ? "pending" : index % 6 === 0 ? "needs_changes" : index % 5 === 0 ? "approved" : undefined,
  };
});

export const artifacts: Artifact[] = [
  artifact("artifact-001", "run-daily-001", "collect", "json", "source-health-summary.json", 18422, "2026-05-22T23:40:00Z", "{\n  \"healthy\": 4,\n  \"degraded\": 2,\n  \"failed\": 1,\n  \"disabled\": 1\n}"),
  artifact("artifact-002", "run-daily-001", "report", "markdown", "daily-ai-infrastructure.md", 42210, "2026-05-22T23:44:00Z", "# 每日 AI 基础设施\n\nAgent 运行时可观测性仍是今天最强的运营信号。"),
  artifact("artifact-003", "run-daily-001", "publish", "html", "daily-ai-infrastructure.html", 66810, "2026-05-22T23:46:00Z", "<article><h1>每日 AI 基础设施</h1><p>Trace 证据质量提升。</p></article>"),
  artifact("artifact-004", "run-daily-001", "quality", "log", "quality-gate.log", 9832, "2026-05-22T23:47:00Z", "23:47:01 sourceCoverage 通过\n23:47:02 citationQuality 警告"),
  artifact("artifact-005", "run-weekly-004", "report", "report", "weekly-trend-report.pdf.meta", 12940, "2026-05-22T18:30:00Z", "每周趋势报告元数据和存储引用。"),
  artifact("artifact-006", "run-weekly-004", "dataset", "dataset", "topic-clusters.parquet.meta", 812044, "2026-05-22T18:34:00Z"),
  artifact("artifact-007", "run-memory-002", "memory", "json", "memory-recall-evidence.json", 34812, "2026-05-22T17:12:00Z", "{\n  \"hits\": 42,\n  \"collection\": \"report_sections\"\n}"),
  artifact("artifact-008", "run-source-009", "source", "log", "reddit-rate-limit.log", 6330, "2026-05-22T20:31:00Z", "reddit-localllama 返回 HTTP 429，已启用退避策略。"),
  artifact("artifact-009", "run-topic-003", "topic", "markdown", "agent-runtime-topic-brief.md", 21800, "2026-05-22T21:50:00Z", "## Agent 运行时可观测性\n\nTrace 上下文和策略门控出现在多个来源中。"),
  artifact("artifact-010", "run-quality-006", "quality", "json", "quality-checks.json", 12990, "2026-05-22T16:22:00Z", "{\n  \"failed\": 3,\n  \"review_required\": 5\n}"),
  artifact("artifact-011", "run-report-007", "final", "html", "source-health-report.html", 35120, "2026-05-22T14:10:00Z"),
  artifact("artifact-012", "run-eval-008", "eval", "dataset", "citation-eval-cases.jsonl", 271220, "2026-05-22T12:05:00Z", "{\"case\":\"引用覆盖\",\"expected\":\"warning\"}"),
];

function memory(
  id: string,
  type: MemoryItem["type"],
  title: string,
  summary: string,
  createdAt: string,
  confidence: NonNullable<MemoryItem["confidence"]>,
  score: number,
  tags: string[],
  entityNames: string[],
  topicIds: string[],
  sourceType: NonNullable<MemoryItem["sourceType"]>,
): MemoryItem {
  return {
    id,
    type,
    title,
    summary,
    content: `${summary} 这条记忆会保留给 Studio 可追踪检查和后续报告上下文使用。`,
    createdAt,
    updatedAt: createdAt,
    confidence,
    score,
    relatedObjectIds: [`rel-${id}`],
    relatedObjectType: type === "evidence" ? "evidence" : type === "topic" ? "topic" : type === "report" ? "report" : "news",
    tags,
    entityNames,
    topicIds,
    sourceType,
  };
}

function artifact(
  id: string,
  runId: string,
  stepId: string,
  artifactType: Artifact["artifactType"],
  filename: string,
  sizeBytes: number,
  createdAt: string,
  preview?: string,
): Artifact {
  return {
    id,
    runId,
    stepId,
    artifactType,
    filename,
    sizeBytes,
    createdAt,
    preview,
    url: `/artifacts/${id}`,
  };
}

function makeQualityChecks(index: number, status: QualityResult["status"]): QualityCheck[] {
  const names: QualityCheck["name"][] = [
    "sourceCoverage",
    "factConsistency",
    "duplicateRisk",
    "summaryCompleteness",
    "titleQuality",
    "evidenceCompleteness",
    "citationQuality",
    "humanReviewRequired",
  ];

  return names.map((name, checkIndex) => {
    const shouldFail = status === "failed" && checkIndex % 3 === index % 3;
    const shouldWarn = status === "warning" && checkIndex % 4 === index % 4;
    const reviewWarn = status === "review_required" && (name === "humanReviewRequired" || checkIndex === index % names.length);
    const checkStatus: QualityCheck["status"] = shouldFail ? "failed" : shouldWarn || reviewWarn ? "warning" : "passed";
    return {
      id: `check-${index + 1}-${name}`,
      name,
      status: checkStatus,
      score: checkStatus === "passed" ? 90 - (checkIndex % 5) : checkStatus === "warning" ? 62 + checkIndex : 34 + checkIndex,
      message:
        checkStatus === "passed"
          ? "检查通过，证据充分。"
          : checkStatus === "warning"
            ? "建议发布前复核。"
            : "必需证据不完整，门控失败。",
    };
  });
}

function qualityTitle(index: number, objectType: QualityResult["objectType"]): string {
  const titles = [
    "Agent 运行时 trace 覆盖",
    "本地模型质量漂移",
    "每日 AI 基础设施报告",
    "主题聚类工作流运行",
    "策略更新的引用完整性",
    "社区来源批次的重复风险",
    "多模态基准的来源覆盖",
    "报告标题质量复核",
  ];
  const objectTypeLabels: Record<QualityResult["objectType"], string> = {
    news: "新闻",
    topic: "主题",
    report: "报告",
    run: "运行",
  };
  return `${titles[index % titles.length]}（${objectTypeLabels[objectType]}）`;
}
