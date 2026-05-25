import { apiGet, apiPost } from "@/lib/api/client"
import type { Locale, Paper, PaperAISummary, PaperListResult, PaperPeriod, PaperSort } from "@/lib/papers/types"

type ApiEnvelope<T> = {
  success: boolean
  data?: T | null
  error?: {
    code: string
    message: string
    details?: unknown
    detail?: unknown
    request_id?: string | null
    requestId?: string
    retryable?: boolean
  } | null
  request_id?: string | null
}

export type PaperListParams = {
  q?: string
  period?: PaperPeriod
  sort?: PaperSort
  limit?: number
  offset?: number
  task?: string
  method?: string
}

export class PapersApiError extends Error {
  code: string
  detail?: unknown
  retryable?: boolean

  constructor(message: string, code = "papers_api_error", detail?: unknown, retryable?: boolean) {
    super(message)
    this.name = "PapersApiError"
    this.code = code
    this.detail = detail
    this.retryable = retryable
  }
}

export async function fetchPapers(params: PaperListParams, init?: RequestInit): Promise<PaperListResult> {
  const envelope = await apiGet<ApiEnvelope<PaperListResult>>(`/api/v1/papers${queryString(params)}`, init)
  return unwrapEnvelope(envelope)
}

export async function fetchPaperDetail(paperId: string, init?: RequestInit): Promise<Paper> {
  const envelope = await apiGet<ApiEnvelope<{ paper: Paper }>>(`/api/v1/papers/${encodeURIComponent(paperId)}`, init)
  return unwrapEnvelope(envelope).paper
}

export async function requestPaperSummary(
  paperId: string,
  locale: Locale,
  init?: RequestInit
): Promise<PaperAISummary> {
  const envelope = await apiPost<ApiEnvelope<{ summary: PaperAISummary }>>(
    `/api/v1/papers/${encodeURIComponent(paperId)}/summary?locale=${locale}`,
    undefined,
    init
  )
  return unwrapEnvelope(envelope).summary
}

function unwrapEnvelope<T>(envelope: ApiEnvelope<T>): T {
  if (envelope.success && envelope.data) {
    return envelope.data
  }
  const error = envelope.error
  throw new PapersApiError(
    error?.message ?? "Papers API request failed",
    error?.code,
    error?.detail ?? error?.details,
    error?.retryable
  )
}

function queryString(params: PaperListParams) {
  const searchParams = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") {
      continue
    }
    searchParams.set(key, String(value))
  }
  const text = searchParams.toString()
  return text ? `?${text}` : ""
}
