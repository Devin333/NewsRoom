export type AgentRunStatus =
  | "pending"
  | "running"
  | "success"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "partially_failed"
  | "blocked"
  | "waiting_for_human"

export type StepStatus = "pending" | "running" | "success" | "failed" | "skipped" | "blocked" | "cancelled"

export type AgentStepType =
  | "collect"
  | "process"
  | "rank"
  | "memory"
  | "research"
  | "report"
  | "quality"
  | "final"
  | "custom"

export type AgentRun = {
  id: string
  agentName: string
  workflowId?: string
  workflowName?: string
  workflowVersion?: string
  profile: string
  status: AgentRunStatus
  startedAt: string
  finishedAt?: string
  durationMs?: number
  durationSeconds: number
  inputCount: number
  outputCount: number
  artifactCount: number
  artifactDir?: string
  qualityScore?: number
  errorCount: number
  eventCount?: number
  reportId?: string
  manifestPath?: string
  dataState?: "ready" | "partial" | "fallback"
  notices?: string[]
  stepCount?: number
  steps?: Array<{
    id: string
    label: string
    status: StepStatus
  }>
}

export type AgentStep = {
  id: string
  runId: string
  nodeId: string
  label: string
  type: AgentStepType
  status: StepStatus
  startedAt?: string
  finishedAt?: string
  durationMs?: number
  inputPreview?: unknown
  outputPreview?: unknown
  errorMessage?: string
  artifactIds?: string[]
  raw?: unknown
}

export type WorkflowDagNode = {
  id: string
  stepId: string
  label: string
  type: AgentStep["type"]
  status: StepStatus
  durationMs?: number
  inputCount?: number
  outputCount?: number
  errorMessage?: string
}

export type WorkflowDagEdge = {
  id: string
  source: string
  target: string
  label?: string
}

export type RunLogItem = {
  id: string
  timestamp: string
  level: "debug" | "info" | "warning" | "error"
  message: string
  stepId?: string
  eventType?: string
  payload?: unknown
}

export type ToolCall = {
  id: string
  runId: string
  stepId?: string
  toolName: string
  status: "pending" | "running" | "success" | "failed"
  startedAt: string
  finishedAt?: string
  durationMs?: number
  argsPreview?: unknown
  resultPreview?: unknown
  errorMessage?: string
}

export type MemoryHit = {
  id: string
  runId: string
  stepId?: string
  memoryId: string
  memoryType: "news" | "topic" | "evidence" | "entity" | "report" | "agent_note"
  score: number
  summary: string
  relatedTopicName?: string
  relatedEvidenceId?: string
  createdAt?: string
}

export type Artifact = {
  id: string
  runId: string
  stepId?: string
  artifactType: "json" | "markdown" | "html" | "log" | "report" | "dataset"
  filename: string
  sizeBytes?: number
  createdAt: string
  preview?: string
  url?: string
}

export type RunQualitySummary = {
  runId: string
  score?: number
  status: "passed" | "warning" | "failed" | "review_required"
  checks: {
    id: string
    name: string
    status: "passed" | "warning" | "failed"
    message?: string
  }[]
}

export type RunErrorTrace = {
  id: string
  runId: string
  stepId?: string
  timestamp: string
  message: string
  stackPreview?: string
  retryHint?: string
}

export type AgentRunFilters = {
  keyword?: string
  agentName?: string[]
  workflowId?: string[]
  status?: AgentRunStatus[]
  profile?: string[]
  dateRange?: "today" | "week" | "month" | "custom"
  hasError?: boolean
  minQualityScore?: number
  sort?: "startedAt" | "durationMs" | "qualityScore" | "errorCount"
}

export type StudioOverview = {
  activeRuns: number
  failedRuns24h: number
  completedRuns24h: number
  avgDurationMs?: number
  avgQualityScore?: number
  artifactsGenerated24h: number
  qualityReviewRequired: number
  latestRuns: AgentRun[]
}

export type AgentRunDetail = {
  run: AgentRun
  steps: AgentStep[]
  dag: {
    nodes: WorkflowDagNode[]
    edges: WorkflowDagEdge[]
  }
  logs: RunLogItem[]
  toolCalls: ToolCall[]
  memoryHits: MemoryHit[]
  artifacts: Artifact[]
  quality?: RunQualitySummary
  errors: RunErrorTrace[]
  dataState: "ready" | "partial" | "fallback"
  notices: string[]
}

export type StudioDataState = "ready" | "partial" | "fallback"

export type StudioRunListItem = AgentRun & {
  workflowId?: string
  workflowVersion?: string
  reportId?: string
  artifactDir?: string
  eventCount?: number
  manifestPath?: string
  dataState: StudioDataState
  notices: string[]
}

export type StudioRunOperations = {
  canCancel: boolean
  canRerunFromStep: boolean
  canSkipStep: boolean
  canResolveBlocked: boolean
}

export type StudioRunDetail = AgentRunDetail & {
  run: StudioRunListItem
  events: RunLogItem[]
  diagnostics?: Record<string, unknown>
  health?: Record<string, unknown>
  operations: StudioRunOperations
  dataState: StudioDataState
  notices: string[]
}

export type RunOperationType = "cancel" | "rerun-from-step" | "skip-step" | "mark-blocked-resolved"

export type RunOperationPayload = {
  reason: string
  stepId?: string
  actorId?: string
  resolvedBy?: string
  resolutionType?: string
  metadata?: Record<string, unknown>
}

export type RunOperationResult = {
  ok: boolean
  operationType?: string
  status?: string
  message?: string
  requestId?: string
  raw?: unknown
}
