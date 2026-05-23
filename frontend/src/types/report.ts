export type ReportType = "daily" | "weekly" | "topic" | "tech" | "quality" | "source_health"

export type ReportStatus = "draft" | "generated" | "reviewed" | "published" | "failed"

export type Report = {
  id: string
  title: string
  type?: ReportType
  reportType?: ReportType
  markdown?: string
  generatedAt: string
  coveredFrom?: string
  coveredTo?: string
  agentName?: string
  qualityScore?: number
  topicIds?: string[]
  newsItemIds?: string[]
  evidenceIds?: string[]
  status: ReportStatus
}
