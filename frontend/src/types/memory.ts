import type { SourceType } from "@/types/common"

export type MemoryItem = {
  id: string
  type: "news" | "topic" | "evidence" | "entity" | "report" | "agent_note"
  title: string
  summary: string
  content?: string
  createdAt: string
  updatedAt?: string
  confidence?: "high" | "medium" | "low"
  score?: number
  relatedObjectIds?: string[]
  relatedObjectType?: "news" | "topic" | "report" | "evidence"
  tags: string[]
  entityNames?: string[]
  topicIds?: string[]
  sourceType?: SourceType
}

export type MemoryFilters = {
  keyword?: string
  memoryType?: MemoryItem["type"][]
  entity?: string
  topicId?: string
  sourceType?: SourceType[]
  dateRange?: "today" | "week" | "month" | "custom"
  confidence?: ("high" | "medium" | "low")[]
}

export type MemoryViewMode = "list" | "evidence" | "entity" | "topic" | "timeline"
