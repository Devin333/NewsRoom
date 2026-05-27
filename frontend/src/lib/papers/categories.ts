import type { Locale, PaperTask } from "@/lib/papers/types"

export const aiTaskGroups = [
  "agents",
  "language-models",
  "reasoning",
  "multimodal",
  "computer-vision",
  "speech-audio",
  "code-ai",
  "robotics-embodied",
  "retrieval-knowledge",
  "data-evaluation",
  "systems-infra",
  "security-safety",
  "ai-for-science",
  "human-ai-interaction"
] as const

export type AiTaskGroup = (typeof aiTaskGroups)[number]

export const benchmarkCategories = [
  "language-understanding",
  "language-generation",
  "question-answering",
  "reasoning-math",
  "reasoning-logic",
  "long-context",
  "instruction-following",
  "alignment-preference",
  "agent-task-completion",
  "tool-use",
  "code-generation",
  "software-engineering",
  "retrieval-search",
  "knowledge-graph",
  "image-classification",
  "object-detection",
  "segmentation",
  "image-generation",
  "video-understanding",
  "video-generation",
  "visual-question-answering",
  "multimodal-reasoning",
  "ocr-document-understanding",
  "speech-recognition",
  "speech-generation",
  "audio-understanding",
  "music-generation",
  "robotics-manipulation",
  "robotics-navigation",
  "embodied-control",
  "medical-imaging",
  "biomedical-nlp",
  "scientific-discovery",
  "time-series-forecasting",
  "graph-learning",
  "recommendation-ranking",
  "safety-robustness",
  "privacy-security",
  "efficiency-systems",
  "data-quality-evaluation"
] as const

export type BenchmarkCategory = (typeof benchmarkCategories)[number]

const taskGroupLabels: Record<AiTaskGroup, Record<Locale, string>> = {
  agents: { zh: "智能体", en: "Agents" },
  "language-models": { zh: "语言模型", en: "Language Models" },
  reasoning: { zh: "推理", en: "Reasoning" },
  multimodal: { zh: "多模态", en: "Multimodal" },
  "computer-vision": { zh: "计算机视觉", en: "Computer Vision" },
  "speech-audio": { zh: "语音与音频", en: "Speech & Audio" },
  "code-ai": { zh: "代码 AI", en: "Code AI" },
  "robotics-embodied": { zh: "机器人与具身智能", en: "Robotics & Embodied AI" },
  "retrieval-knowledge": { zh: "检索与知识", en: "Retrieval & Knowledge" },
  "data-evaluation": { zh: "数据与评测", en: "Data & Evaluation" },
  "systems-infra": { zh: "系统与基础设施", en: "Systems & Infra" },
  "security-safety": { zh: "安全与对齐", en: "Security & Safety" },
  "ai-for-science": { zh: "AI for Science", en: "AI for Science" },
  "human-ai-interaction": { zh: "人机协作", en: "Human-AI Interaction" }
}

const benchmarkCategoryLabels: Partial<Record<BenchmarkCategory, Record<Locale, string>>> = {
  "question-answering": { zh: "问答", en: "Question Answering" },
  "reasoning-math": { zh: "数学推理", en: "Math Reasoning" },
  "reasoning-logic": { zh: "逻辑推理", en: "Logic Reasoning" },
  "agent-task-completion": { zh: "智能体任务完成", en: "Agent Task Completion" },
  "tool-use": { zh: "工具使用", en: "Tool Use" },
  "code-generation": { zh: "代码生成", en: "Code Generation" },
  "software-engineering": { zh: "软件工程", en: "Software Engineering" },
  "retrieval-search": { zh: "检索搜索", en: "Retrieval & Search" },
  "visual-question-answering": { zh: "视觉问答", en: "Visual QA" },
  "multimodal-reasoning": { zh: "多模态推理", en: "Multimodal Reasoning" },
  "efficiency-systems": { zh: "效率与系统", en: "Efficiency & Systems" },
  "data-quality-evaluation": { zh: "数据质量评测", en: "Data Quality Evaluation" }
}

export function taskGroupLabel(group: string | undefined, locale: Locale) {
  const normalized = normalizeTaskGroup(group)
  return normalized ? taskGroupLabels[normalized][locale] : titleFromSlug(group ?? "Unclassified")
}

export function benchmarkCategoryLabel(category: string | undefined, locale: Locale) {
  const normalized = normalizeBenchmarkCategory(category)
  if (!normalized) {
    return undefined
  }
  return benchmarkCategoryLabels[normalized]?.[locale] ?? titleFromSlug(normalized)
}

export function orderedTaskGroups(tasks: PaperTask[]) {
  const known = new Set(aiTaskGroups)
  const groups = new Set(tasks.map((task) => task.group).filter(Boolean))
  return [
    ...aiTaskGroups.filter((group) => groups.has(group)),
    ...Array.from(groups)
      .filter((group) => !known.has(group as AiTaskGroup))
      .sort((left, right) => left.localeCompare(right))
  ]
}

export function normalizeTaskGroup(group: string | undefined): AiTaskGroup | undefined {
  return aiTaskGroups.find((item) => item === group)
}

export function normalizeBenchmarkCategory(category: string | undefined): BenchmarkCategory | undefined {
  return benchmarkCategories.find((item) => item === category)
}

function titleFromSlug(value: string) {
  return value
    .split("-")
    .filter(Boolean)
    .map((part) => (part.length <= 3 ? part.toUpperCase() : part[0].toUpperCase() + part.slice(1)))
    .join(" ")
}
