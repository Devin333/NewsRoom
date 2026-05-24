export type Locale = "zh" | "en"

export type PaperModuleSection =
  | "trending_papers"
  | "tasks"
  | "task_detail"
  | "methods"
  | "method_detail"

export type PaperModuleRoute =
  | "/papers"
  | "/papers/tasks"
  | `/papers/tasks/${string}`
  | "/papers/methods"
  | `/papers/methods/${string}`

export type PaperSort = "trending" | "newest" | "most_cited"

export interface TaskRef {
  id: string
  slug: string
  name: string
  nameZh?: string
}

export interface MethodRef {
  id: string
  slug: string
  name: string
  nameZh?: string
}

export interface BenchmarkRef {
  id: string
  slug: string
  name: string
}

export interface Paper {
  id: string
  slug: string
  title: string
  titleZh?: string
  abstractSnippet: string
  abstractSnippetZh?: string
  authors: string[]
  publishedAt: string
  venue?: string
  citationCount?: number
  citationDoi?: string
  githubMomentum?: number
  thumbnailUrl?: string
  tags: string[]
  taskRefs: TaskRef[]
  methodRefs: MethodRef[]
  githubStars?: number
  starsPerHour?: number
  paperUrl?: string
  arxivUrl?: string
  pdfUrl?: string
  repoUrl?: string
  isPublished: boolean
}

export interface PaperTask {
  id: string
  slug: string
  name: string
  nameZh?: string
  group:
    | "general"
    | "vision"
    | "video"
    | "language"
    | "audio"
    | "robotics"
    | "infra"
    | string
  description: string
  descriptionZh?: string
  paperCount: number
  benchmarkCount: number
  methodCount: number
  trendSignal?: string
  sisterTasks: TaskRef[]
  commonMethods: MethodRef[]
}

export interface PaperMethod {
  id: string
  slug: string
  name: string
  nameZh?: string
  description: string
  descriptionZh?: string
  paperCount: number
  taskCount: number
  implementationCount?: number
  area: string
  relatedTasks: TaskRef[]
  relatedMethods: MethodRef[]
  commonBenchmarks?: BenchmarkRef[]
}

export interface Benchmark {
  id: string
  slug: string
  name: string
  taskSlug?: string
  methodSlug?: string
  entryCount: number
  metric?: string
  bestValue?: string | number
}
