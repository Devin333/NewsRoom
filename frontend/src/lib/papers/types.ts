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
export type PaperPeriod = "daily" | "weekly" | "monthly" | "all"

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

export interface PaperImplementation {
  id: string
  name: string
  repoUrl: string
  provider?: string
  githubStars?: number
}

export interface PaperBenchmarkResult {
  id: string
  name: string
  metric?: string
  value?: string | number
  taskSlug?: string
  url?: string
}

export interface PaperAISummary {
  paperId: string
  locale: Locale
  modelRoute: string
  abstractHash: string
  summary: string
  keyInsights: string[]
  limitations: string[]
  generatedAt: string
  cached: boolean
}

export interface PaperSourceRef {
  sourceId?: string
  sourceName?: string
  sourceType?: string
  url?: string
  externalId?: string
  title?: string
}

export interface PaperEvidenceRef extends PaperSourceRef {
  evidenceId?: string
  summary?: string
  quote?: string
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
  newsroomHeatScore?: number
  arxivId?: string
  paperUrl?: string
  arxivUrl?: string
  pdfUrl?: string
  repoUrl?: string
  projectUrl?: string
  implementations?: PaperImplementation[]
  benchmarks?: PaperBenchmarkResult[]
  aiSummary?: PaperAISummary
  evidenceRefs?: PaperEvidenceRef[]
  sourceRefs?: PaperSourceRef[]
  isPublished: boolean
}

export interface PaperListResult {
  source?: string
  query: string
  period: PaperPeriod
  sort: PaperSort
  task?: string
  method?: string
  collectedAt?: string
  paper_count: number
  total_count: number
  source_count: number
  limit: number
  offset: number
  has_next?: boolean
  papers: Paper[]
}

export interface PaperSection {
  id: string
  paperId: string
  title: string
  level: number
  pageStart?: number
  pageEnd?: number
  textExcerpt: string
  summary?: string
  sectionType:
    | "abstract"
    | "summary"
    | "contribution"
    | "introduction"
    | "related_work"
    | "method"
    | "experiment"
    | "result"
    | "limitation"
    | "implementation"
    | "benchmark"
    | "evidence"
    | "conclusion"
    | "appendix"
    | "unknown"
}

export interface PaperReaderQuality {
  paperId: string
  pdfAvailable: boolean
  textExtracted: boolean
  summaryAvailable: boolean
  implementationVerified: boolean
  benchmarkVerified: boolean
  evidenceCoverage: number
  lastUpdatedAt?: string | null
}

export interface RelatedPaper {
  id: string
  title: string
  slug: string
  relationReason: string
  score: number
  venue?: string
  publishedAt?: string
  paperUrl?: string
}

export interface RelatedProject {
  id: string
  name: string
  url?: string
  sourceType: "implementation" | "repository" | "project" | string
  relationReason: string
  score: number
  githubStars?: number
}

export interface RelatedNews {
  id: string
  title: string
  url?: string
  sourceType: string
  relationReason: string
  score: number
  summary?: string
}

export interface PaperReaderPayload {
  paper: Paper
  sections: PaperSection[]
  aiSummary: PaperAISummary | null
  readerNotes: unknown[]
  relatedPapers: RelatedPaper[]
  relatedProjects: RelatedProject[]
  relatedNews: RelatedNews[]
  quality: PaperReaderQuality
}

export interface PaperReaderCitation {
  id: string
  label: string
  sourceType: "section" | "evidence" | "source" | string
  sectionId?: string
  evidenceId?: string
  sourceId?: string
  textExcerpt?: string
  url?: string
}

export interface PaperReaderAnswer {
  paperId: string
  locale: Locale
  question: string
  answer: string
  citations: PaperReaderCitation[]
  confidence: number
  generatedAt: string
  cached: boolean
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
