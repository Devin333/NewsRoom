import type { CredibilityLevel, SourceType } from "@/types/common"

export type EvidenceItem = {
  id: string
  title: string
  sourceName: string
  sourceType: SourceType
  sourceUrl?: string
  originalUrl?: string
  capturedAt: string
  summary?: string
  quote?: string
  credibility: CredibilityLevel
  confidenceScore?: number
  relationReason: string
}

export type Evidence = EvidenceItem
