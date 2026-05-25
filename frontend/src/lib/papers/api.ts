import { apiGet, apiPost } from "@/lib/api/client"
import type {
  Locale,
  Paper,
  PaperAISummary,
  PaperListResult,
  PaperMethod,
  PaperPeriod,
  PaperReaderAnswer,
  PaperReaderPayload,
  PaperRelationGraph,
  PaperSection,
  PaperTask,
  RelatedPaper,
  PaperSort
} from "@/lib/papers/types"

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

export type PaperSummaryRequestOptions = {
  refresh?: boolean
  reason?: string
  init?: RequestInit
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
  const envelope = await apiGet<ApiEnvelope<PaperListResult>>(`/api/papers${queryString(params)}`, init)
  return unwrapEnvelope(envelope)
}

export async function fetchPaperDetail(paperId: string, init?: RequestInit): Promise<Paper> {
  const envelope = await apiGet<ApiEnvelope<{ paper: Paper }>>(`/api/papers/${encodeURIComponent(paperId)}`, init)
  return unwrapEnvelope(envelope).paper
}

export async function requestPaperSummary(
  paperId: string,
  locale: Locale,
  options?: RequestInit | PaperSummaryRequestOptions
): Promise<PaperAISummary> {
  const requestOptions = normalizeSummaryRequestOptions(options)
  const searchParams = new URLSearchParams({ locale })
  if (requestOptions.refresh) {
    searchParams.set("refresh", "true")
  }
  const envelope = await apiPost<ApiEnvelope<{ summary: PaperAISummary }>>(
    `/api/papers/${encodeURIComponent(paperId)}/summary?${searchParams.toString()}`,
    requestOptions.refresh ? { reason: requestOptions.reason } : undefined,
    requestOptions.init
  )
  return unwrapEnvelope(envelope).summary
}

export async function refreshPaperSummary(
  paperId: string,
  locale: Locale,
  reason: string,
  init?: RequestInit
): Promise<PaperAISummary> {
  return requestPaperSummary(paperId, locale, {
    refresh: true,
    reason,
    init,
  })
}

export async function fetchPaperReaderPayload(
  paperId: string,
  locale: Locale,
  init?: RequestInit
): Promise<PaperReaderPayload> {
  const envelope = await apiGet<ApiEnvelope<{ reader: PaperReaderPayload }>>(
    `/api/papers/${encodeURIComponent(paperId)}/reader?locale=${locale}`,
    init
  )
  return unwrapEnvelope(envelope).reader
}

export async function fetchPaperSections(
  paperId: string,
  locale: Locale,
  init?: RequestInit
): Promise<PaperSection[]> {
  const envelope = await apiGet<ApiEnvelope<{ sections: PaperSection[] }>>(
    `/api/papers/${encodeURIComponent(paperId)}/sections?locale=${locale}`,
    init
  )
  return unwrapEnvelope(envelope).sections
}

export async function fetchPaperRelated(paperId: string, init?: RequestInit): Promise<RelatedPaper[]> {
  const envelope = await apiGet<ApiEnvelope<{ relatedPapers: RelatedPaper[] }>>(
    `/api/papers/${encodeURIComponent(paperId)}/related`,
    init
  )
  return unwrapEnvelope(envelope).relatedPapers
}

export async function fetchPaperGraph(paperId: string, init?: RequestInit): Promise<PaperRelationGraph> {
  const envelope = await apiGet<ApiEnvelope<{ graph: PaperRelationGraph }>>(
    `/api/papers/${encodeURIComponent(paperId)}/graph`,
    init
  )
  return unwrapEnvelope(envelope).graph
}

export async function fetchPaperTasks(init?: RequestInit): Promise<PaperTask[]> {
  const envelope = await apiGet<ApiEnvelope<{ tasks: PaperTask[] }>>("/api/papers/tasks", init)
  return unwrapEnvelope(envelope).tasks
}

export async function fetchPaperMethods(init?: RequestInit): Promise<PaperMethod[]> {
  const envelope = await apiGet<ApiEnvelope<{ methods: PaperMethod[] }>>("/api/papers/methods", init)
  return unwrapEnvelope(envelope).methods
}

export async function askPaper(
  paperId: string,
  question: string,
  locale: Locale,
  init?: RequestInit
): Promise<PaperReaderAnswer> {
  const envelope = await apiPost<ApiEnvelope<{ answer: PaperReaderAnswer }>>(
    `/api/papers/${encodeURIComponent(paperId)}/ask`,
    { question, locale },
    init
  )
  return unwrapEnvelope(envelope).answer
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

function normalizeSummaryRequestOptions(options?: RequestInit | PaperSummaryRequestOptions): PaperSummaryRequestOptions {
  if (!options) {
    return {}
  }
  if ("refresh" in options || "reason" in options || "init" in options) {
    return options as PaperSummaryRequestOptions
  }
  return { init: options as RequestInit }
}
