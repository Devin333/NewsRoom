export type AdminLang = "zh" | "en"

export type LocalizedText = {
  zh: string
  en: string
}

export type AdminPage =
  | "overview"
  | "ingestion"
  | "pipeline"
  | "review"
  | "content"
  | "topics"
  | "sources"
  | "agents"
  | "gates"
  | "publishing"
  | "settings"

export type AdminStatus = "ok" | "warning" | "failed" | "review" | "running" | "blocked"

export type AdminNavItem = {
  id: AdminPage
  label: LocalizedText
  purpose: LocalizedText
}

export type AdminMetric = {
  id: string
  label: LocalizedText
  value: string
  delta: LocalizedText
  status: AdminStatus
}

export type ReviewTask = {
  id: string
  title: LocalizedText
  taskType: LocalizedText
  status: LocalizedText
  source: string
  confidence: number
  gate: LocalizedText
  risk: LocalizedText
  priority: LocalizedText
  reason: LocalizedText
  rawInput: LocalizedText
  aiOutput: LocalizedText
  evidence: LocalizedText[]
}

export type AttentionItem = {
  id: string
  reviewId: string
  title: LocalizedText
  type: LocalizedText
  priority: LocalizedText
  reason: LocalizedText
}

export type PipelineNode = {
  id: string
  name: string
  status: AdminStatus
  processed: number
  duration: string
  detail: LocalizedText
  output: LocalizedText
  artifactPath: string
}

export type SourceRecord = {
  id: string
  name: string
  type: LocalizedText
  status: AdminStatus
  lastFetch: LocalizedText
  itemCount: number
  reliability: number
  frequency: LocalizedText
  retryPolicy: LocalizedText
  latestItems: LocalizedText[]
}

export type DraftRecord = {
  id: string
  title: LocalizedText
  body: LocalizedText
  status: LocalizedText
}

export type TopicCluster = {
  id: string
  name: LocalizedText
  itemCount: number
  velocity: LocalizedText
  suggestedAction: LocalizedText
  tags: LocalizedText[]
}

export type AgentRecord = {
  id: string
  name: string
  runCount: number
  successRate: string
  cost: string
  status: AdminStatus
  tools: string[]
  trace: LocalizedText[]
}

export type QualityGate = {
  id: string
  name: LocalizedText
  rule: LocalizedText
  passed: number
  warning: number
  failed: number
  status: AdminStatus
}

export type PublishingChannel = {
  id: string
  name: string
  description: LocalizedText
  readyCount: number
}
