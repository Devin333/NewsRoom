import type { Locale, PaperSort } from "@/lib/papers/types"

export type Localized<T = string> = Record<Locale, T>

export const papersCopy = {
  brand: { zh: "NewsRoom Research", en: "NewsRoom Research" },
  brandSubline: { zh: "Papers · Tasks · Methods", en: "Papers · Tasks · Methods" },
  papersNav: { zh: "Papers", en: "Papers" },
  trendingPapers: { zh: "热门论文", en: "Trending Papers" },
  tasks: { zh: "Tasks 任务", en: "Tasks" },
  methods: { zh: "Methods 方法", en: "Methods" },
  searchPlaceholder: { zh: "搜索论文、任务、方法...", en: "Search papers, tasks, methods..." },
  openNavigation: { zh: "打开 Papers 导航", en: "Open Papers navigation" },
  themeLight: { zh: "切换到浅色模式", en: "Switch to light mode" },
  themeDark: { zh: "切换到深色模式", en: "Switch to dark mode" },
  lightMode: { zh: "浅色", en: "Light" },
  darkMode: { zh: "深色", en: "Dark" },
  languageToggle: { zh: "切换语言", en: "Switch language" },
  dropdownTrendingDescription: {
    zh: "论文流：缩略图、摘要、标签、代码热度。",
    en: "Paper stream with thumbnails, abstracts, tags, and code momentum."
  },
  dropdownTasksDescription: {
    zh: "Papers 分支下的研究任务和领域目录。",
    en: "Research tasks and domain catalog inside Papers."
  },
  dropdownMethodsDescription: {
    zh: "论文相关方法、模型结构、技术路线。",
    en: "Methods, model structures, and technical routes tied to papers."
  },
  frontendView: {
    zh: "前台用户视图 · 已发布研究内容",
    en: "Frontend user view · approved research content"
  },
  taskBranch: { zh: "Papers 分支 · Tasks", en: "Papers branch · Tasks" },
  methodBranch: { zh: "Papers 分支 · Methods", en: "Papers branch · Methods" },
  taskDetailMeta: {
    zh: "公开任务详情 · Benchmarks + Papers",
    en: "Public task detail · benchmarks + papers"
  },
  methodDetailMeta: {
    zh: "公开方法详情 · Papers + Tasks",
    en: "Public method detail · papers + tasks"
  },
  researchPapers: { zh: "Research Papers 研究论文", en: "Research Papers" },
  researchSubtitle: {
    zh: "通过任务、方法、代码热度和证据型元数据快速浏览已发布的 AI 研究。",
    en: "Scan published AI research through task and method signals, code momentum, and evidence-oriented metadata."
  },
  tasksSubtitle: {
    zh: "按研究问题和任务领域浏览 Papers 模块下的论文。",
    en: "Browse research problems and task areas under the Papers module."
  },
  methodsSubtitle: {
    zh: "探索论文中的模型结构、推理范式和技术路线。",
    en: "Explore model structures, reasoning patterns, and technical routes found in papers."
  },
  papers: { zh: "论文", en: "papers" },
  repositories: { zh: "仓库", en: "repos" },
  benchmarks: { zh: "评测", en: "benchmarks" },
  implementations: { zh: "实现", en: "implementations" },
  methodsUsed: { zh: "使用方法", en: "methods used" },
  topDomains: { zh: "Top Domains 热门方向", en: "Top Domains" },
  trendingDomains: { zh: "Trending Domains 趋势方向", en: "Trending Domains" },
  contentPanel: { zh: "Content Panel", en: "Content Panel" },
  benchmarksTitle: { zh: "Benchmarks", en: "Benchmarks" },
  papersUnderTask: { zh: "该任务下的论文", en: "Papers under this task" },
  papersUsingMethod: { zh: "使用该方法的论文", en: "Papers using this method" },
  relatedTasks: { zh: "相关任务", en: "Related Tasks" },
  sisterTasks: { zh: "相邻任务", en: "Sister Tasks" },
  commonMethods: { zh: "常用方法", en: "Common Methods" },
  relatedMethods: { zh: "相关方法", en: "Related Methods" },
  commonBenchmarks: { zh: "常见评测", en: "Common Benchmarks" },
  noPapers: { zh: "暂无匹配论文", en: "No matching papers" },
  openPaper: { zh: "打开论文", en: "Open paper" },
  openCode: { zh: "打开代码仓库", en: "Open code repository" },
  githubStars: { zh: "GitHub stars", en: "GitHub stars" },
  starsPerHour: { zh: "stars / 小时", en: "stars / hr" },
  citations: { zh: "引用", en: "citations" },
  paperRecord: { zh: "论文", en: "paper" },
  paperPreview: {
    zh: "当前 v0.5 先使用论文预览提示，后续版本可加入独立论文详情页。",
    en: "Paper detail is mocked in this v0.5 scope. A future version can add a dedicated paper detail route."
  },
  benchmarkPreview: {
    zh: "当前版本的 Benchmark 详情先作为模拟操作处理。",
    en: "Benchmark detail is a mock action for this version."
  },
  dismiss: { zh: "关闭", en: "Dismiss" }
} satisfies Record<string, Localized>

export const sortLabels: Record<PaperSort, Localized> = {
  trending: { zh: "趋势", en: "trending" },
  newest: { zh: "最新", en: "newest" },
  most_cited: { zh: "高引用", en: "most cited" }
}

export const taskGroupLabels: Record<string, Localized> = {
  general: { zh: "General 通用", en: "General" },
  vision: { zh: "Vision 视觉", en: "Vision" },
  video: { zh: "Video 视频", en: "Video" },
  language: { zh: "Language 语言", en: "Language" },
  audio: { zh: "Audio 音频", en: "Audio" },
  robotics: { zh: "Robotics 机器人", en: "Robotics" },
  infra: { zh: "Infra 基础设施", en: "Infra" }
}

export function t(value: Localized | undefined, locale: Locale, fallback = "") {
  if (!value) {
    return fallback
  }
  return value[locale] ?? value.en ?? fallback
}
