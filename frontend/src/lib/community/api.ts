import { apiGet } from "@/lib/api/client"
import {
  communitySignalFiltersToSearchParams
} from "@/lib/community/community-signals"
import type {
  CommunityListParams,
  CommunityListResult,
  CommunitySignalDetailResult,
  CommunitySignalListParams,
  CommunitySignalListResult,
  CommunityTopicDetail
} from "@/types/community"

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

export class CommunityApiError extends Error {
  code: string
  detail?: unknown
  retryable?: boolean

  constructor(message: string, code = "community_api_error", detail?: unknown, retryable?: boolean) {
    super(message)
    this.name = "CommunityApiError"
    this.code = code
    this.detail = detail
    this.retryable = retryable
  }
}

export async function fetchCommunityTopics(
  params: CommunityListParams = {},
  init?: RequestInit
): Promise<CommunityListResult> {
  const envelope = await apiGet<ApiEnvelope<CommunityListResult>>(`/api/community${queryString(params)}`, init)
  return unwrapEnvelope(envelope)
}

export async function fetchCommunityTopic(slug: string, init?: RequestInit): Promise<CommunityTopicDetail> {
  const envelope = await apiGet<ApiEnvelope<{ topic: CommunityTopicDetail }>>(
    `/api/community/topics/${encodeURIComponent(slug)}`,
    init
  )
  return unwrapEnvelope(envelope).topic
}

export async function fetchCommunitySignals(
  params: CommunitySignalListParams = {},
  init?: RequestInit
): Promise<CommunitySignalListResult> {
  const query = communitySignalFiltersToSearchParams(params)
  const envelope = await apiGet<ApiEnvelope<CommunitySignalListResult>>(
    `/api/community/signals${query.size ? `?${query.toString()}` : ""}`,
    init
  )
  return unwrapEnvelope(envelope)
}

export async function fetchCommunitySignal(signalId: string, init?: RequestInit): Promise<CommunitySignalDetailResult> {
  const envelope = await apiGet<ApiEnvelope<CommunitySignalDetailResult>>(
    `/api/community/signals/${encodeURIComponent(signalId)}`,
    init
  )
  return unwrapEnvelope(envelope)
}

function unwrapEnvelope<T>(envelope: ApiEnvelope<T>): T {
  if (envelope.success && envelope.data !== undefined && envelope.data !== null) {
    return envelope.data
  }
  const error = envelope.error
  throw new CommunityApiError(
    error?.message ?? "Community API request failed",
    error?.code,
    error?.detail ?? error?.details,
    error?.retryable
  )
}

function queryString(params: CommunityListParams) {
  const searchParams = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue
    searchParams.set(key, String(value))
  }
  const text = searchParams.toString()
  return text ? `?${text}` : ""
}
