import { safeApiGet, type SafeApiResult } from "@/lib/api/server"

export type ApiRunList = {
  run_count?: number
  runs?: ApiRunListItem[]
}

export type ApiRunListItem = {
  run_id?: string | null
  id?: string | null
  workflow_id?: string | null
  workflow_name?: string | null
  workflow_version?: string | null
  profile?: string | null
  status?: string | null
  started_at?: string | null
  finished_at?: string | null
  report_id?: string | null
  artifact_dir?: string | null
  quality_score?: number | null
  step_count?: number | null
  event_count?: number | null
  artifact_count?: number | null
  error_count?: number | null
  manifest_path?: string | null
}

export type ApiRunDetail = ApiRunListItem & {
  manifest?: Record<string, unknown> | null
  output_preview?: Record<string, unknown> | null
  error?: Record<string, unknown> | string | null
  metrics?: Record<string, unknown> | null
}

export type ApiRunStep = {
  step_id?: string | null
  id?: string | null
  sequence?: number | null
  label?: string | null
  type?: string | null
  status?: string | null
  started_at?: string | null
  finished_at?: string | null
  output_keys?: string[] | null
  error?: Record<string, unknown> | string | null
  metrics?: Record<string, unknown> | null
  artifact_refs?: unknown[] | null
  raw?: Record<string, unknown> | null
}

export type ApiRunSteps = {
  step_count?: number
  steps?: ApiRunStep[]
}

export type ApiRunEvent = {
  event_id?: string | null
  id?: string | null
  event_type?: string | null
  step_id?: string | null
  timestamp?: string | null
  created_at?: string | null
  occurred_at?: string | null
  level?: string | null
  message?: string | null
  payload?: Record<string, unknown> | null
}

export type ApiRunEvents = {
  event_count?: number
  events?: ApiRunEvent[]
}

export type ApiRunArtifact = {
  artifact_key?: string | null
  relative_path?: string | null
  content_type?: string | null
  size_bytes?: number | null
  content?: unknown
  url?: string | null
  read_error?: string | null
}

export type ApiRunArtifacts = {
  artifact_count?: number
  artifacts?: ApiRunArtifact[]
}

export type ApiRunDiagnostics = {
  diagnostics?: Record<string, unknown> | null
}

export type ApiRunHealth = {
  health?: Record<string, unknown> | null
}

export type RunCenterDetailResponses = {
  detail: SafeApiResult<ApiRunDetail>
  steps: SafeApiResult<ApiRunSteps>
  events: SafeApiResult<ApiRunEvents>
  diagnostics: SafeApiResult<ApiRunDiagnostics>
  health: SafeApiResult<ApiRunHealth>
  artifacts: SafeApiResult<ApiRunArtifacts>
}

export async function fetchRunCenterList(): Promise<SafeApiResult<ApiRunList>> {
  return safeApiGet<ApiRunList>("/api/v1/runs?limit=50")
}

export async function fetchRunCenterDetail(runId: string): Promise<RunCenterDetailResponses> {
  const encodedRunId = encodeURIComponent(decodeURIComponent(runId))
  const [detail, steps, events, diagnostics, health, artifacts] = await Promise.all([
    safeApiGet<ApiRunDetail>(`/api/v1/runs/${encodedRunId}`),
    safeApiGet<ApiRunSteps>(`/api/v1/runs/${encodedRunId}/steps`),
    safeApiGet<ApiRunEvents>(`/api/v1/runs/${encodedRunId}/events?limit=100`),
    safeApiGet<ApiRunDiagnostics>(`/api/v1/runs/${encodedRunId}/diagnostics`),
    safeApiGet<ApiRunHealth>(`/api/v1/runs/${encodedRunId}/health`),
    safeApiGet<ApiRunArtifacts>(`/api/v1/runs/${encodedRunId}/artifacts`)
  ])

  return { detail, steps, events, diagnostics, health, artifacts }
}
