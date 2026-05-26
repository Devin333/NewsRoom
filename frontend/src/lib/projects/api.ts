import { apiGet } from "@/lib/api/client"
import type { ProjectDetailResult, ProjectItem, ProjectListParams, ProjectListResult } from "@/types/projects"

type ApiEnvelope<T> = {
  success: boolean
  data?: T | null
  error?: {
    code: string
    message: string
    detail?: unknown
    details?: unknown
    retryable?: boolean
  } | null
}

export class ProjectsApiError extends Error {
  code: string
  detail?: unknown
  retryable?: boolean

  constructor(message: string, code = "projects_api_error", detail?: unknown, retryable?: boolean) {
    super(message)
    this.name = "ProjectsApiError"
    this.code = code
    this.detail = detail
    this.retryable = retryable
  }
}

export async function fetchProjects(params: ProjectListParams = {}, init?: RequestInit): Promise<ProjectListResult> {
  const envelope = await apiGet<ApiEnvelope<ProjectListResult>>(`/api/projects${queryString(params)}`, init)
  return unwrapEnvelope(envelope)
}

export async function fetchProjectDetail(slug: string, init?: RequestInit): Promise<ProjectItem> {
  const envelope = await apiGet<ApiEnvelope<ProjectDetailResult>>(`/api/projects/${encodeURIComponent(slug)}`, init)
  return unwrapEnvelope(envelope).project
}

function unwrapEnvelope<T>(envelope: ApiEnvelope<T>): T {
  if (envelope.success && envelope.data) {
    return envelope.data
  }
  const error = envelope.error
  throw new ProjectsApiError(
    error?.message ?? "Projects API request failed",
    error?.code,
    error?.detail ?? error?.details,
    error?.retryable
  )
}

function queryString(params: ProjectListParams): string {
  const searchParams = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue
    searchParams.set(key, String(value))
  }
  const text = searchParams.toString()
  return text ? `?${text}` : ""
}
