import type { ApiError, ApiResponse } from "@/lib/types"

const DEFAULT_API_BASE_URL = "http://localhost:8000"

export class NewsRoomApiError extends Error {
  code: string
  details: Record<string, unknown>
  requestId?: string
  statusCode?: number

  constructor(error: ApiError, statusCode?: number) {
    super(error.message)
    this.name = "NewsRoomApiError"
    this.code = error.code
    this.details = error.details ?? {}
    this.requestId = error.request_id ?? undefined
    this.statusCode = statusCode
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  return apiRequest<T>("GET", path)
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  return apiRequest<T>("POST", path, body)
}

export async function safeApiGet<T>(path: string) {
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
    const message = error instanceof Error ? error.message : "Request failed"
    return {
      ok: false,
      errorCode: "request_failed",
      errorMessage: message
    }
  }
}

export async function safeApiPost<T>(path: string, body: unknown) {
  try {
    return { ok: true, data: await apiPost<T>(path, body) }
  } catch (error) {
    if (error instanceof NewsRoomApiError) {
      return {
        ok: false,
        errorCode: error.code,
        errorMessage: error.message,
        requestId: error.requestId
      }
    }
    const message = error instanceof Error ? error.message : "Request failed"
    return {
      ok: false,
      errorCode: "request_failed",
      errorMessage: message
    }
  }
}

async function apiRequest<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
  const response = await fetch(apiUrl(path), {
    method,
    headers: headers(body !== undefined),
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store"
  })
  const payload = (await response.json()) as ApiResponse<T>

  if (!payload.success) {
    throw new NewsRoomApiError(
      payload.error ?? {
        code: "api_error",
        message: "API request failed",
        details: {},
        retryable: false,
        user_action_required: false,
        request_id: payload.request_id
      },
      response.status
    )
  }

  return payload.data as T
}

function apiUrl(path: string): string {
  const baseUrl = process.env.NEWSROOM_API_BASE_URL ?? DEFAULT_API_BASE_URL
  if (path.startsWith("http://") || path.startsWith("https://")) {
    return path
  }
  const suffix = path.startsWith("/") ? path : `/${path}`
  return `${baseUrl.replace(/\/$/, "")}${suffix}`
}

function headers(hasBody: boolean): HeadersInit {
  const result: Record<string, string> = {
    Accept: "application/json"
  }
  if (hasBody) {
    result["Content-Type"] = "application/json"
  }
  if (process.env.NEWSROOM_API_TOKEN) {
    result.Authorization = `Bearer ${process.env.NEWSROOM_API_TOKEN}`
  }
  return result
}
