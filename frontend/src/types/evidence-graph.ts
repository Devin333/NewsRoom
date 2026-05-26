export type EvidenceNodeType =
  | "topic"
  | "paper"
  | "project"
  | "news"
  | "community_signal"
  | "company"
  | "model"
  | "method"
  | "task"
  | "report"

export type EvidenceNode = {
  id: string
  type: EvidenceNodeType
  title: string
  summary?: string
  url?: string
  source?: string
  createdAt?: string
  updatedAt?: string
  score?: number
  confidence?: number
  tags?: string[]
  metadata?: Record<string, unknown>
}

export type EvidenceEdgeType =
  | "mentions"
  | "implements"
  | "cites"
  | "discusses"
  | "supports"
  | "contradicts"
  | "derived_from"
  | "same_topic"
  | "released_by"
  | "reported_by"

export type EvidenceEdge = {
  id: string
  sourceNodeId: string
  targetNodeId: string
  type: EvidenceEdgeType
  confidence: number
  evidenceText?: string
  createdAt?: string
  metadata?: Record<string, unknown>
}

export type TopicEvidenceTrajectory = "rising" | "stable" | "declining" | "noisy" | "uncertain"

export type TopicEvidenceSummary = {
  topicId: string
  topicName: string
  summary: string
  trendScore: number
  evidenceScore: number
  confidenceScore: number
  paperCount: number
  projectCount: number
  newsCount: number
  communitySignalCount: number
  firstSeenAt: string
  lastUpdatedAt: string
  trajectory: TopicEvidenceTrajectory
  keyEvidenceNodeIds: string[]
}

export type EvidenceGraphPeriod = "daily" | "weekly" | "monthly" | "all"

export type EvidenceGraphQuery = {
  topic?: string
  entity?: string
  period?: EvidenceGraphPeriod
  nodeTypes?: EvidenceNodeType[]
  depth?: number
  limit?: number
}

export type EvidenceGraphTimelineItem = {
  id: string
  topicId: string
  occurredAt: string
  title: string
  summary: string
  sourceCount: number
  nodeIds: string[]
  importance: "low" | "medium" | "high"
  board: "paper" | "project" | "news" | "community" | "report"
  href?: string
}

export type EvidenceGraphRelatedReport = {
  id: string
  title: string
  href: string
  status?: string
  createdAt?: string
  summary?: string
  evidenceNodeIds: string[]
}

export type EvidenceGraphSourceState = {
  board: "papers" | "projects" | "news" | "community" | "reports"
  state: "ready" | "degraded" | "empty"
  source: string
  count: number
  notices: string[]
}

export type EvidenceGraphResponse = {
  generatedAt: string
  query: EvidenceGraphQuery
  summary: TopicEvidenceSummary
  nodes: EvidenceNode[]
  edges: EvidenceEdge[]
  timeline: EvidenceGraphTimelineItem[]
  relatedReports: EvidenceGraphRelatedReport[]
  sourceStates: EvidenceGraphSourceState[]
  notices: string[]
}

export type EvidenceGraphNodeDetailResponse = {
  node: EvidenceNode
  incomingEdges: EvidenceEdge[]
  outgoingEdges: EvidenceEdge[]
  relatedNodes: EvidenceNode[]
}
