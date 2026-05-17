export type ApiError = {
  code: string
  message: string
  details?: Record<string, unknown>
  retryable: boolean
  user_action_required: boolean
  request_id?: string | null
}

export type ApiResponse<T> = {
  success: boolean
  data?: T | null
  error?: ApiError | null
  request_id: string
  schema_version: string
}

export type LoadResult<T> = {
  ok: boolean
  data?: T
  errorCode?: string
  errorMessage?: string
  requestId?: string
}

export type HealthStatus = {
  status: string
  service?: string
  version?: string
}

export type LatestReport = {
  report_id: string
  run_id: string
  status: string
  title?: string | null
  report_json?: Record<string, unknown> | null
  report_markdown?: string | null
  quality_score?: number | null
  manifest_path?: string | null
}

export type ReportListItem = {
  report_id?: string | null
  run_id: string
  status?: string | null
  summary?: string | null
  title?: string | null
  created_at?: string | null
  published_at?: string | null
  quality_score?: number | null
  citation_coverage_score?: number | null
  source_count?: number | null
  evidence_count?: number | null
  manifest_path?: string | null
  metadata?: Record<string, unknown>
}

export type ReportList = {
  limit?: number
  workflow_id?: string | null
  report_count: number
  reports: ReportListItem[]
}

export type ReportDetail = LatestReport & {
  summary?: string | null
  created_at?: string | null
  published_at?: string | null
  citation_coverage_score?: number | null
  source_count?: number | null
  evidence_count?: number | null
}

export type ReportMarkdown = {
  report_id: string
  run_id?: string | null
  markdown?: string | null
  report_markdown?: string | null
  content?: string | null
}

export type ReportQuality = {
  report_id?: string | null
  run_id?: string | null
  quality_score?: number | null
  quality_result?: Record<string, unknown> | null
  checks?: unknown[]
}

export type RunListItem = {
  run_id: string
  workflow_id?: string | null
  workflow_version?: string | null
  profile?: string | null
  status: string
  started_at?: string | null
  finished_at?: string | null
  report_id?: string | null
  artifact_dir?: string | null
}

export type RunList = {
  run_count: number
  runs: RunListItem[]
}

export type RunDetail = RunListItem & {
  manifest?: Record<string, unknown>
  output_preview?: Record<string, unknown>
  error?: Record<string, unknown> | null
  metrics?: Record<string, unknown>
  manifest_path?: string | null
}

export type RunEvent = {
  event_id?: string | null
  event_type: string
  step_id?: string | null
  created_at?: string | null
  occurred_at?: string | null
  payload?: Record<string, unknown>
}

export type RunEvents = {
  run_id: string
  event_count: number
  events: RunEvent[]
  events_path?: string | null
}

export type RunArtifact = {
  artifact_key: string
  relative_path?: string | null
  content_type?: string | null
  size_bytes?: number | null
  read_error?: string | null
}

export type RunArtifacts = {
  run_id: string
  artifact_count: number
  artifacts: RunArtifact[]
}

export type RunDiagnostics = {
  run_id: string
  diagnostics?: Record<string, unknown>
}

export type RunOperationResult = {
  operation_id: string
  operation_type: string
  status: string
  run_id: string
  message: string
  new_run_id?: string | null
  details?: Record<string, unknown>
}

export type WorkerSummary = {
  worker_count?: number
  workers?: unknown[]
  queues?: unknown[]
}

export type WorkerStatus = {
  worker_id?: string | null
  status?: string | null
  queue_name?: string | null
  current_task_id?: string | null
  leased_until?: string | null
  heartbeat_at?: string | null
  metadata?: Record<string, unknown>
}

export type QueueStatus = {
  queue_name?: string | null
  pending_count?: number | null
  leased_count?: number | null
  dead_letter_count?: number | null
  stale_count?: number | null
  metadata?: Record<string, unknown>
}

export type WorkerStatusResponse = WorkerSummary & {
  worker_count?: number
  queue_count?: number
  workers?: WorkerStatus[]
  queues?: QueueStatus[]
}

export type SourceHealthItem = {
  source_id: string
  source_name?: string | null
  status: string
  last_success_at?: string | null
  last_failure_at?: string | null
  consecutive_failures?: number | null
  cooldown_until?: string | null
  last_error?: string | null
}

export type SourceHealthResponse = {
  source_count?: number
  sources?: SourceHealthItem[]
  health?: SourceHealthItem[]
}

export type MemorySearchResult = {
  document_id?: string | null
  collection?: string | null
  score?: number | null
  text?: string | null
  metadata?: Record<string, unknown>
}

export type MemorySearchResponse = {
  collection: string
  query: string
  filters?: Record<string, unknown>
  limit: number
  result_count: number
  results: MemorySearchResult[]
}

export type ApprovalItem = {
  approval_id: string
  requested_action?: string | null
  status: string
  risk_level?: string | null
  reason?: string | null
  requested_by?: string | null
  created_at?: string | null
  expires_at?: string | null
  payload?: Record<string, unknown>
}

export type ApprovalListResponse = {
  approval_count?: number
  approvals?: ApprovalItem[]
  items?: ApprovalItem[]
}
