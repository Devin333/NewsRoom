import type { Benchmark, BenchmarkRef, MethodRef, Paper, PaperMethod, PaperTask, TaskRef } from "@/lib/papers/types"

const taskRefs = {
  agents: { id: "task-agents", slug: "agents", name: "Agents", nameZh: "Agents 智能体" },
  codingAgents: { id: "task-coding-agents", slug: "coding-agents", name: "Coding Agents", nameZh: "代码智能体" },
  computerUseAgents: { id: "task-computer-use-agents", slug: "computer-use-agents", name: "Computer Use Agents", nameZh: "计算机操作智能体" },
  documentUnderstanding: { id: "task-document-understanding", slug: "document-understanding", name: "Document Understanding", nameZh: "文档理解" },
  embeddingModels: { id: "task-embedding-models", slug: "embedding-models", name: "Embedding Models", nameZh: "嵌入模型" },
  languageModeling: { id: "task-language-modeling", slug: "language-modeling", name: "Language Modeling", nameZh: "语言建模" },
  ocr: { id: "task-ocr", slug: "ocr", name: "OCR" },
  omniModels: { id: "task-omni-models", slug: "omni-models", name: "Omni Models", nameZh: "全模态模型" },
  reasoning: { id: "task-reasoning", slug: "reasoning", name: "Reasoning", nameZh: "推理" },
  visualQuestionAnswering: { id: "task-visual-question-answering", slug: "visual-question-answering", name: "Visual QA", nameZh: "视觉问答" },
  videoUnderstanding: { id: "task-video-understanding", slug: "video-understanding", name: "Video Understanding", nameZh: "视频理解" },
  speechRecognition: { id: "task-speech-recognition", slug: "speech-recognition", name: "Speech Recognition", nameZh: "语音识别" },
  robotManipulation: { id: "task-robot-manipulation", slug: "robot-manipulation", name: "Robot Manipulation", nameZh: "机器人操作" },
  inferenceServing: { id: "task-inference-serving", slug: "inference-serving", name: "Inference Serving", nameZh: "推理服务" }
} satisfies Record<string, TaskRef>

const methodRefs = {
  llm: { id: "method-llm", slug: "large-language-model", name: "Large Language Model (LLM)", nameZh: "大语言模型 (LLM)" },
  react: { id: "method-react", slug: "react", name: "ReAct" },
  agent: { id: "method-agent", slug: "agent", name: "Agent", nameZh: "智能体" },
  deepseekR1: { id: "method-deepseek-r1", slug: "deepseek-r1", name: "DeepSeek-R1" },
  grpo: { id: "method-grpo", slug: "grpo", name: "GRPO" },
  qwen3: { id: "method-qwen3", slug: "qwen3", name: "Qwen3" },
  rag: { id: "method-rag", slug: "rag", name: "RAG" },
  postTraining: { id: "method-post-training", slug: "post-training", name: "Post-training", nameZh: "后训练" },
  toolUse: { id: "method-tool-use", slug: "tool-use", name: "Tool Use", nameZh: "工具使用" },
  chainOfThought: { id: "method-chain-of-thought", slug: "chain-of-thought", name: "Chain-of-Thought", nameZh: "思维链" },
  planning: { id: "method-planning", slug: "planning", name: "Planning", nameZh: "规划" },
  agentMemory: { id: "method-agent-memory", slug: "agent-memory", name: "Agent Memory", nameZh: "智能体记忆" }
} satisfies Record<string, MethodRef>

const benchmarkRefs = {
  clawEval: { id: "benchmark-claw-eval", slug: "claw-eval", name: "Claw-Eval" },
  browseComp: { id: "benchmark-browsecomp", slug: "browsecomp", name: "BrowseComp" },
  tau2Bench: { id: "benchmark-tau2-bench", slug: "tau2-bench", name: "τ²-Bench" },
  bfclV4: { id: "benchmark-bfcl-v4", slug: "bfcl-v4", name: "BFCL-v4" },
  mcpAtlas: { id: "benchmark-mcpatlas", slug: "mcpatlas", name: "MCPAtlas" },
  toolBench: { id: "benchmark-toolbench", slug: "toolbench", name: "ToolBench" }
} satisfies Record<string, BenchmarkRef>

export const paperTasks: PaperTask[] = [
  {
    ...taskRefs.agents,
    group: "general",
    description: "Agent systems that reason, call tools, use memory, and complete multi-step tasks.",
    descriptionZh: "能够推理、调用工具、使用记忆并完成多步骤任务的 Agent 系统。",
    paperCount: 992,
    benchmarkCount: 5,
    methodCount: 8,
    trendSignal: "+1.4x",
    sisterTasks: [
      taskRefs.codingAgents,
      taskRefs.computerUseAgents,
      taskRefs.documentUnderstanding,
      taskRefs.embeddingModels,
      taskRefs.languageModeling,
      taskRefs.ocr,
      taskRefs.omniModels,
      taskRefs.reasoning
    ],
    commonMethods: [
      methodRefs.llm,
      methodRefs.react,
      methodRefs.agent,
      methodRefs.deepseekR1,
      methodRefs.grpo,
      methodRefs.qwen3,
      methodRefs.rag,
      methodRefs.postTraining
    ]
  },
  {
    ...taskRefs.reasoning,
    group: "general",
    description: "Reasoning tasks for multi-step inference, planning, and verification.",
    descriptionZh: "面向多步推理、规划和验证的研究任务。",
    paperCount: 713,
    benchmarkCount: 18,
    methodCount: 11,
    trendSignal: "+1.2x",
    sisterTasks: [taskRefs.agents, taskRefs.languageModeling, taskRefs.codingAgents],
    commonMethods: [methodRefs.chainOfThought, methodRefs.react, methodRefs.planning, methodRefs.grpo]
  },
  {
    ...taskRefs.visualQuestionAnswering,
    group: "vision",
    description: "Answering questions grounded in images, charts, documents, and diagrams.",
    descriptionZh: "围绕图像、图表、文档和示意图进行问答。",
    paperCount: 846,
    benchmarkCount: 32,
    methodCount: 9,
    trendSignal: "+18%",
    sisterTasks: [taskRefs.documentUnderstanding, taskRefs.ocr, taskRefs.omniModels],
    commonMethods: [methodRefs.llm, methodRefs.rag, methodRefs.toolUse]
  },
  {
    ...taskRefs.videoUnderstanding,
    group: "video",
    description: "Understanding temporal visual content and action sequences.",
    descriptionZh: "理解时间序列视觉内容和动作过程。",
    paperCount: 328,
    benchmarkCount: 14,
    methodCount: 7,
    trendSignal: "+22%",
    sisterTasks: [taskRefs.visualQuestionAnswering, taskRefs.omniModels],
    commonMethods: [methodRefs.llm, methodRefs.planning]
  },
  {
    ...taskRefs.languageModeling,
    group: "language",
    description: "Modeling language distributions, instruction following, and generation behavior.",
    descriptionZh: "建模语言分布、指令跟随和生成行为。",
    paperCount: 1402,
    benchmarkCount: 41,
    methodCount: 15,
    trendSignal: "+9%",
    sisterTasks: [taskRefs.reasoning, taskRefs.embeddingModels, taskRefs.agents],
    commonMethods: [methodRefs.llm, methodRefs.postTraining, methodRefs.grpo, methodRefs.qwen3]
  },
  {
    ...taskRefs.speechRecognition,
    group: "audio",
    description: "Recognizing and transcribing spoken language across noisy or multilingual settings.",
    descriptionZh: "在嘈杂或多语言场景下识别并转写语音。",
    paperCount: 271,
    benchmarkCount: 12,
    methodCount: 6,
    trendSignal: "+7%",
    sisterTasks: [taskRefs.omniModels, taskRefs.languageModeling],
    commonMethods: [methodRefs.llm, methodRefs.postTraining]
  },
  {
    ...taskRefs.robotManipulation,
    group: "robotics",
    description: "Policies and controllers for physical manipulation tasks.",
    descriptionZh: "面向物理操作任务的策略和控制器。",
    paperCount: 214,
    benchmarkCount: 9,
    methodCount: 5,
    trendSignal: "+16%",
    sisterTasks: [taskRefs.agents, taskRefs.visualQuestionAnswering],
    commonMethods: [methodRefs.planning, methodRefs.agent, methodRefs.toolUse]
  },
  {
    ...taskRefs.inferenceServing,
    group: "infra",
    description: "Serving systems, routing, and optimization for deployed AI workloads.",
    descriptionZh: "面向已部署 AI 工作负载的服务系统、路由和优化。",
    paperCount: 189,
    benchmarkCount: 8,
    methodCount: 6,
    trendSignal: "+12%",
    sisterTasks: [taskRefs.languageModeling, taskRefs.embeddingModels],
    commonMethods: [methodRefs.rag, methodRefs.llm]
  },
  {
    ...taskRefs.codingAgents,
    group: "general",
    description: "Agents that plan and apply code changes in repositories.",
    descriptionZh: "能够在代码仓库中规划并应用代码修改的智能体。",
    paperCount: 388,
    benchmarkCount: 11,
    methodCount: 8,
    trendSignal: "+1.3x",
    sisterTasks: [taskRefs.agents, taskRefs.computerUseAgents, taskRefs.reasoning],
    commonMethods: [methodRefs.react, methodRefs.toolUse, methodRefs.rag, methodRefs.planning]
  },
  {
    ...taskRefs.computerUseAgents,
    group: "general",
    description: "Agents that operate browsers, desktops, and software interfaces.",
    descriptionZh: "能够操作浏览器、桌面和软件界面的智能体。",
    paperCount: 254,
    benchmarkCount: 7,
    methodCount: 7,
    trendSignal: "+1.1x",
    sisterTasks: [taskRefs.agents, taskRefs.codingAgents, taskRefs.documentUnderstanding],
    commonMethods: [methodRefs.react, methodRefs.toolUse, methodRefs.planning]
  },
  {
    ...taskRefs.documentUnderstanding,
    group: "vision",
    description: "Understanding document layouts, tables, forms, and long visual text.",
    descriptionZh: "理解文档版式、表格、表单和长视觉文本。",
    paperCount: 522,
    benchmarkCount: 21,
    methodCount: 8,
    trendSignal: "+15%",
    sisterTasks: [taskRefs.ocr, taskRefs.visualQuestionAnswering, taskRefs.agents],
    commonMethods: [methodRefs.rag, methodRefs.toolUse, methodRefs.llm]
  },
  {
    ...taskRefs.embeddingModels,
    group: "language",
    description: "Representation models for retrieval, clustering, and semantic search.",
    descriptionZh: "用于检索、聚类和语义搜索的表示模型。",
    paperCount: 467,
    benchmarkCount: 16,
    methodCount: 6,
    trendSignal: "+11%",
    sisterTasks: [taskRefs.languageModeling, taskRefs.agents],
    commonMethods: [methodRefs.rag, methodRefs.postTraining]
  },
  {
    ...taskRefs.ocr,
    group: "vision",
    description: "Extracting text from images, documents, and noisy visual sources.",
    descriptionZh: "从图像、文档和噪声视觉来源中提取文本。",
    paperCount: 301,
    benchmarkCount: 13,
    methodCount: 5,
    trendSignal: "+8%",
    sisterTasks: [taskRefs.documentUnderstanding, taskRefs.visualQuestionAnswering],
    commonMethods: [methodRefs.llm, methodRefs.toolUse]
  },
  {
    ...taskRefs.omniModels,
    group: "video",
    description: "Models that combine language, image, video, and audio capabilities.",
    descriptionZh: "融合语言、图像、视频和音频能力的模型。",
    paperCount: 363,
    benchmarkCount: 17,
    methodCount: 9,
    trendSignal: "+24%",
    sisterTasks: [taskRefs.visualQuestionAnswering, taskRefs.videoUnderstanding, taskRefs.speechRecognition],
    commonMethods: [methodRefs.llm, methodRefs.postTraining, methodRefs.toolUse]
  }
]

export const paperMethods: PaperMethod[] = [
  {
    ...methodRefs.react,
    description: "Reasoning + Acting loop for tool-using agents.",
    descriptionZh: "面向工具使用 Agent 的 Reasoning + Acting 循环。",
    paperCount: 42,
    taskCount: 12,
    implementationCount: 18,
    area: "Agents",
    relatedTasks: [
      taskRefs.agents,
      taskRefs.codingAgents,
      taskRefs.computerUseAgents,
      taskRefs.reasoning,
      taskRefs.languageModeling
    ],
    relatedMethods: [
      methodRefs.toolUse,
      methodRefs.chainOfThought,
      methodRefs.rag,
      methodRefs.planning,
      methodRefs.agentMemory,
      methodRefs.postTraining
    ],
    commonBenchmarks: [benchmarkRefs.clawEval, benchmarkRefs.browseComp, benchmarkRefs.bfclV4, benchmarkRefs.toolBench]
  },
  {
    ...methodRefs.toolUse,
    description: "Calling external tools, APIs, and functions with evidence-aware control.",
    descriptionZh: "在证据感知控制下调用外部工具、API 和函数。",
    paperCount: 67,
    taskCount: 18,
    implementationCount: 24,
    area: "Agents",
    relatedTasks: [taskRefs.agents, taskRefs.computerUseAgents, taskRefs.codingAgents],
    relatedMethods: [methodRefs.react, methodRefs.planning, methodRefs.agentMemory, methodRefs.rag],
    commonBenchmarks: [benchmarkRefs.bfclV4, benchmarkRefs.toolBench]
  },
  {
    ...methodRefs.chainOfThought,
    description: "Intermediate reasoning traces used to improve multi-step problem solving.",
    descriptionZh: "通过中间推理轨迹提升多步问题求解能力。",
    paperCount: 91,
    taskCount: 23,
    implementationCount: 31,
    area: "Reasoning",
    relatedTasks: [taskRefs.reasoning, taskRefs.languageModeling, taskRefs.agents],
    relatedMethods: [methodRefs.react, methodRefs.grpo, methodRefs.postTraining],
    commonBenchmarks: [benchmarkRefs.browseComp, benchmarkRefs.tau2Bench]
  },
  {
    ...methodRefs.rag,
    description: "Retrieval-augmented generation for grounding model answers in external evidence.",
    descriptionZh: "通过检索增强生成，把模型回答锚定在外部证据上。",
    paperCount: 104,
    taskCount: 27,
    implementationCount: 44,
    area: "Retrieval",
    relatedTasks: [taskRefs.documentUnderstanding, taskRefs.embeddingModels, taskRefs.agents],
    relatedMethods: [methodRefs.agentMemory, methodRefs.toolUse, methodRefs.llm],
    commonBenchmarks: [benchmarkRefs.mcpAtlas, benchmarkRefs.toolBench]
  },
  {
    ...methodRefs.planning,
    description: "Task decomposition and action sequencing for long-horizon systems.",
    descriptionZh: "面向长程系统的任务分解和动作序列规划。",
    paperCount: 56,
    taskCount: 14,
    implementationCount: 19,
    area: "Agents",
    relatedTasks: [taskRefs.agents, taskRefs.robotManipulation, taskRefs.computerUseAgents],
    relatedMethods: [methodRefs.react, methodRefs.toolUse, methodRefs.agentMemory],
    commonBenchmarks: [benchmarkRefs.clawEval, benchmarkRefs.browseComp]
  },
  {
    ...methodRefs.postTraining,
    description: "Post-training recipes for instruction following, preference alignment, and reasoning.",
    descriptionZh: "面向指令跟随、偏好对齐和推理能力的后训练方案。",
    paperCount: 88,
    taskCount: 21,
    implementationCount: 29,
    area: "Language Models",
    relatedTasks: [taskRefs.languageModeling, taskRefs.reasoning, taskRefs.omniModels],
    relatedMethods: [methodRefs.grpo, methodRefs.deepseekR1, methodRefs.qwen3],
    commonBenchmarks: [benchmarkRefs.browseComp, benchmarkRefs.tau2Bench]
  },
  {
    ...methodRefs.agentMemory,
    description: "Memory structures that preserve context, events, and evidence across agent runs.",
    descriptionZh: "在智能体运行之间保留上下文、事件和证据的记忆结构。",
    paperCount: 35,
    taskCount: 9,
    implementationCount: 12,
    area: "Agents",
    relatedTasks: [taskRefs.agents, taskRefs.codingAgents, taskRefs.documentUnderstanding],
    relatedMethods: [methodRefs.rag, methodRefs.react, methodRefs.toolUse],
    commonBenchmarks: [benchmarkRefs.mcpAtlas, benchmarkRefs.clawEval]
  }
]

export const benchmarks: Benchmark[] = [
  { ...benchmarkRefs.clawEval, taskSlug: "agents", methodSlug: "react", entryCount: 29, metric: "success", bestValue: "73.2" },
  { ...benchmarkRefs.browseComp, taskSlug: "agents", methodSlug: "react", entryCount: 25, metric: "accuracy", bestValue: "61.4" },
  { ...benchmarkRefs.tau2Bench, taskSlug: "agents", methodSlug: "chain-of-thought", entryCount: 15, metric: "score", bestValue: "58.8" },
  { ...benchmarkRefs.bfclV4, taskSlug: "agents", methodSlug: "tool-use", entryCount: 7, metric: "pass@1", bestValue: "82.0" },
  { ...benchmarkRefs.mcpAtlas, taskSlug: "agents", methodSlug: "rag", entryCount: 4, metric: "coverage", bestValue: "76.5" },
  { ...benchmarkRefs.toolBench, taskSlug: "computer-use-agents", methodSlug: "tool-use", entryCount: 31, metric: "win rate", bestValue: "67.1" }
]

export const papers: Paper[] = [
  {
    id: "paper-agent-lightning",
    slug: "agent-lightning",
    title: "Agent Lightning: Train ANY AI Agents with Reinforcement Learning",
    titleZh: "Agent Lightning: Train ANY AI Agents with Reinforcement Learning",
    abstractSnippet:
      "We present Agent Lightning, a flexible and extensible framework that enables Reinforcement Learning-based training of Large Language Models for any AI agent.",
    abstractSnippetZh:
      "Agent Lightning 是一个灵活、可扩展的框架，用于以强化学习方式训练任意 AI Agent。",
    authors: ["Xufang Luo", "Yuge Zhang", "Zhiyuan He", "+5 authors"],
    publishedAt: "2025-08-05",
    venue: "arXiv",
    citationCount: 36,
    tags: ["reinforcement learning"],
    taskRefs: [taskRefs.agents, taskRefs.languageModeling],
    methodRefs: [methodRefs.agent],
    githubStars: 9900,
    starsPerHour: 4,
    arxivUrl: "https://arxiv.org/abs/2508.03680",
    pdfUrl: "https://arxiv.org/pdf/2508.03680.pdf",
    repoUrl: "https://github.com/",
    isPublished: true
  },
  {
    id: "paper-tooluseverify",
    slug: "tooluseverify",
    title: "ToolUseVerify: Benchmarking Faithful Tool Use in Language Agents",
    titleZh: "ToolUseVerify：评测语言智能体的可信工具使用",
    abstractSnippet:
      "A benchmark that checks whether language agents call tools for the right reason and use returned evidence in final answers.",
    abstractSnippetZh:
      "一个用于检查语言智能体是否因正确原因调用工具，并在最终回答中使用返回证据的评测。",
    authors: ["Amir Patel", "Nora Klein", "Yu Tan"],
    publishedAt: "2026-05-12",
    venue: "ICML Workshop",
    citationCount: 134,
    tags: ["tool use", "agent evaluation", "evidence"],
    taskRefs: [taskRefs.agents, taskRefs.reasoning],
    methodRefs: [methodRefs.toolUse, methodRefs.react],
    githubStars: 3200,
    starsPerHour: 18.1,
    paperUrl: "https://paperswithcode.com/",
    repoUrl: "https://github.com/",
    isPublished: true
  },
  {
    id: "paper-repository-aware-code-agents",
    slug: "repository-aware-code-agents",
    title: "Repository-Aware Retrieval for Code Generation Agents",
    titleZh: "面向代码生成智能体的仓库感知检索",
    abstractSnippet:
      "A retrieval plan that combines symbol graphs, dependency topology, and commit recency for repository-scale coding agents.",
    abstractSnippetZh:
      "一种结合符号图、依赖拓扑和提交新鲜度的检索方案，用于仓库级代码智能体。",
    authors: ["Daniel Kim", "Priya Raman", "Noah Fischer"],
    publishedAt: "2026-04-30",
    venue: "arXiv",
    citationCount: 209,
    tags: ["coding agents", "repository retrieval", "Graph RAG"],
    taskRefs: [taskRefs.codingAgents, taskRefs.agents],
    methodRefs: [methodRefs.rag, methodRefs.planning, methodRefs.toolUse],
    githubStars: 1510,
    starsPerHour: 7.6,
    arxivUrl: "https://arxiv.org/",
    repoUrl: "https://github.com/",
    isPublished: true
  },
  {
    id: "paper-small-vlm-agents",
    slug: "small-vlm-agents",
    title: "Small Vision-Language Agents Can Self-Route Visual Tasks",
    titleZh: "小型视觉语言智能体可以自路由视觉任务",
    abstractSnippet:
      "A compact VLM agent learns when to answer directly, invoke OCR, call detection models, or request high-resolution crops.",
    abstractSnippetZh:
      "一个紧凑型 VLM 智能体学习何时直接回答、调用 OCR、调用检测模型或请求高分辨率裁剪。",
    authors: ["Sofia Mendes", "Hiro Sato", "Leah Brooks"],
    publishedAt: "2026-05-07",
    venue: "CVPR",
    citationCount: 172,
    tags: ["VLM", "tool routing", "document AI"],
    taskRefs: [taskRefs.visualQuestionAnswering, taskRefs.documentUnderstanding, taskRefs.ocr],
    methodRefs: [methodRefs.toolUse, methodRefs.planning],
    githubStars: 870,
    starsPerHour: 4.8,
    arxivUrl: "https://arxiv.org/",
    repoUrl: "https://github.com/",
    isPublished: true
  },
  {
    id: "paper-react-revisited",
    slug: "react-revisited",
    title: "ReAct Revisited: Stable Reasoning-Acting Loops for Browser Agents",
    titleZh: "重新审视 ReAct：面向浏览器智能体的稳定推理-行动循环",
    abstractSnippet:
      "A study of robust ReAct variants for browser tasks, with analysis of tool-call timing and recovery behavior.",
    abstractSnippetZh:
      "一项关于浏览器任务中稳健 ReAct 变体的研究，并分析工具调用时机和恢复行为。",
    authors: ["Hannah Lee", "Omar Haddad", "Ivy Chang"],
    publishedAt: "2026-04-21",
    venue: "ACL Findings",
    citationCount: 245,
    tags: ["ReAct", "browser agents", "planning"],
    taskRefs: [taskRefs.agents, taskRefs.computerUseAgents, taskRefs.reasoning],
    methodRefs: [methodRefs.react, methodRefs.toolUse, methodRefs.planning],
    githubStars: 1290,
    starsPerHour: 6.2,
    paperUrl: "https://example.com/",
    repoUrl: "https://github.com/",
    isPublished: true
  },
  {
    id: "paper-distilled-robot-policies",
    slug: "distilled-robot-policies",
    title: "Distilling Web-Scale Robot Policies into Task-Specific Controllers",
    titleZh: "将 Web 规模机器人策略蒸馏为任务专用控制器",
    abstractSnippet:
      "A robotics distillation pipeline that extracts task-specific controllers and keeps safety guards explicit.",
    abstractSnippetZh:
      "一个机器人策略蒸馏流程，用于提取任务专用控制器，并保持安全约束显式可见。",
    authors: ["Elena Petrova", "Marco Silva", "Chen Rong"],
    publishedAt: "2026-04-22",
    venue: "RSS",
    citationCount: 98,
    tags: ["robotics", "policy distillation", "safety"],
    taskRefs: [taskRefs.robotManipulation, taskRefs.agents],
    methodRefs: [methodRefs.planning, methodRefs.agent],
    githubStars: 420,
    starsPerHour: 2.1,
    paperUrl: "https://example.com/",
    isPublished: true
  }
]

export const topDomains = [taskRefs.agents, taskRefs.languageModeling, taskRefs.visualQuestionAnswering, taskRefs.reasoning]
export const trendingDomains = [taskRefs.codingAgents, taskRefs.computerUseAgents, taskRefs.documentUnderstanding, taskRefs.omniModels]

export function getTaskBySlug(slug: string) {
  return paperTasks.find((task) => task.slug === slug)
}

export function getMethodBySlug(slug: string) {
  return paperMethods.find((method) => method.slug === slug)
}

export function getPapersForTask(slug: string) {
  return papers.filter((paper) => paper.taskRefs.some((task) => task.slug === slug))
}

export function getPapersForMethod(slug: string) {
  return papers.filter((paper) => paper.methodRefs.some((method) => method.slug === slug))
}

export function getBenchmarksForTask(slug: string) {
  return benchmarks.filter((benchmark) => benchmark.taskSlug === slug)
}

export function getBenchmarksForMethod(slug: string) {
  return benchmarks.filter((benchmark) => benchmark.methodSlug === slug)
}

export function getTaskRef(slug: string) {
  return Object.values(taskRefs).find((task) => task.slug === slug)
}

export function getMethodRef(slug: string) {
  return Object.values(methodRefs).find((method) => method.slug === slug)
}
