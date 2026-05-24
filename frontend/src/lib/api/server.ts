import type { ApiError } from "@/types/common"

const DEFAULT_API_BASE_URL = "http://localhost:8000"

type ApiEnvelope<T> = {
  success?: boolean
  data?: T | null
  error?: (ApiError & { details?: unknown; request_id?: string | null }) | null
  request_id?: string | null
}

export type SafeApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; errorCode: string; errorMessage: string; requestId?: string }

export class NewsRoomApiError extends Error {
  code: string
  detail?: unknown
  requestId?: string
  status?: number

  constructor(error: ApiError, status?: number) {
    super(error.message)
    this.name = "NewsRoomApiError"
    this.code = error.code
    this.detail = error.detail
    this.requestId = error.requestId
    this.status = status
  }
}

export async function safeApiGet<T>(path: string): Promise<SafeApiResult<T>> {
  try {
    return { ok: true, data: await apiGet<T>(path) }
  } catch (error) {
    if (error instanceof NewsRoomApiError) {
      return {
        ok: false,
        errorCode: error.code,
        errorMessage: error.message,
        requestId: error.requestId
      }
    }
    return {
      ok: false,
      errorCode: "request_failed",
      errorMessage: error instanceof Error ? error.message : "Request failed"
    }
  }
}

async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(apiUrl(path), {
    method: "GET",
    headers: requestHeaders(),
    cache: "no-store"
  })

  const payload = await parsePayload<T>(response)
  if (!response.ok) {
    throw new NewsRoomApiError(
      {
        code: `http_${response.status}`,
        message: response.statusText || "API request failed",
        detail: payload
      },
      response.status
    )
  }

  if (isApiEnvelope<T>(payload)) {
    if (payload.success === false) {
      const error = payload.error ?? {
        code: "api_error",
        message: "API request failed",
        detail: payload
      }
      throw new NewsRoomApiError(
        {
          code: error.code,
          message: error.message,
          detail: "detail" in error ? error.detail : error.details,
          requestId: error.requestId ?? error.request_id ?? payload.request_id ?? undefined
        },
        response.status
      )
    }
    return payload.data as T
  }

  return payload as T
}

async function parsePayload<T>(response: Response): Promise<T | ApiEnvelope<T> | string> {
  const contentType = response.headers.get("content-type") ?? ""
  if (contentType.includes("application/json")) {
    return (await response.json()) as T | ApiEnvelope<T>
  }
  return response.text()
}

function isApiEnvelope<T>(payload: T | ApiEnvelope<T> | string): payload is ApiEnvelope<T> {
  return typeof payload === "object" && payload !== null && "success" in payload
}

function apiUrl(path: string): string {
  if (path.startsWith("http://") || path.startsWith("https://")) return path
  const baseUrl = process.env.NEWSROOM_API_BASE_URL ?? DEFAULT_API_BASE_URL
  const suffix = path.startsWith("/") ? path : `/${path}`
  return `${baseUrl.replace(/\/$/, "")}${suffix}`
}

function requestHeaders(): HeadersInit {
  const headers: Record<string, string> = {
    Accept: "application/json"
  }
  const apiToken = process.env.NEWSROOM_API_TOKEN ?? process.env.NEWS_API_TOKEN
  if (apiToken) {
    headers.Authorization = `Bearer ${apiToken}`
  }
  return headers
}
