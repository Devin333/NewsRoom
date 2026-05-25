export type { Artifact } from "@/types/agent"

export type ArtifactFilters = {
  keyword: string
  artifactType: "all" | "json" | "markdown" | "html" | "log" | "report" | "dataset"
  runId: string
}

export type ArtifactPreviewKind = "json" | "markdown" | "text" | "html" | "binary" | "unknown"

export type ArtifactDataState = "ready" | "partial" | "fallback"

export type StudioArtifact = {
  artifactKey: string
  runId: string
  relativePath?: string
  contentType?: string
  sizeBytes?: number
  content?: unknown
  readError?: string
  previewKind: ArtifactPreviewKind
  redacted: boolean
  truncated?: boolean
  previewText?: string
  previewNotice?: string
}

export type StudioLineageRef = {
  lineageId?: string
  runId: string
  sourceType: string
  sourceId: string
  targetType: string
  targetId: string
  relationType?: string
  direction: "upstream" | "downstream"
  createdAt?: string
}

export type StudioReplayBundle = {
  runId: string
  manifest: Record<string, unknown>
  manifestPath?: string
  events: Array<Record<string, unknown>>
  eventsPath?: string
  eventsError?: string
  artifacts: StudioArtifact[]
  stepResults: Record<string, unknown>
  integrity: Record<string, unknown>
  eventCount: number
  artifactCount: number
  stepResultCount: number
  ready: boolean
  readinessLabel: string
  notices: string[]
  dataState: ArtifactDataState
}

export type StudioArtifactRunSummary = {
  runId: string
  workflowId?: string
  workflowVersion?: string
  profile?: string
  status: string
  startedAt?: string
  finishedAt?: string
  manifestPath?: string
  artifactCount: number
  eventCount: number
  stepResultCount: number
  artifactStatus: "ready" | "partial" | "missing" | "error"
  notices: string[]
}

export type StudioArtifactRunDetail = {
  run: StudioArtifactRunSummary
  manifest: Record<string, unknown>
  artifacts: StudioArtifact[]
  selectedArtifact?: StudioArtifact
  replay?: StudioReplayBundle
  lineage: StudioLineageRef[]
  notices: string[]
  dataState: ArtifactDataState
}
