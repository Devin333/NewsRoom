import type { CredibilityLevel, SourceType } from "@/types/common"

export type { CredibilityLevel, SourceType }

export type SourceHealthStatus = "healthy" | "degraded" | "failed" | "disabled"

export type SourceHealth = {
  id: string
  name: string
  type: SourceType
  status: SourceHealthStatus
  successRate: number
  lastCheckedAt: string
}

export type SourceRunHistory = {
  id: string
  status: SourceHealthStatus
  startedAt: string
  finishedAt?: string
  collectedCount: number
  latencyMs?: number
  errorMessage?: string
}

export type SourcePreviewItem = {
  id: string
  title: string
  capturedAt: string
  url?: string
}

export type Source = {
  id: string
  name: string
  type: SourceType
  enabled: boolean
  healthStatus: SourceHealthStatus
  lastRunAt?: string
  lastSuccessAt?: string
  errorCount24h: number
  collectedCount24h: number
  avgLatencyMs?: number
  configProfile?: string
  recentRuns?: SourceRunHistory[]
  errorSummary?: string[]
  latestItems?: SourcePreviewItem[]
  configSummary?: string
}

export type SourceFilters = {
  keyword: string
  type: "all" | SourceType
  healthStatus: "all" | SourceHealthStatus
  enabled: "all" | "enabled" | "disabled"
}
