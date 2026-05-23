import type { ApiError } from "@/types/common"
import { resolveMockPath } from "@/lib/api/mock-data"

const DEFAULT_API_BASE_URL = "http://localhost:8000"

export class ApiRequestError extends Error {
  code: string
  detail?: unknown
  requestId?: string
  status?: number

  constructor(error: ApiError, status?: number) {
    super(error.message)
    this.name = "ApiRequestError"
    this.code = error.code
    this.detail = error.detail
    this.requestId = error.requestId
    this.status = status
  }
}

export async function apiGet<T>(path: string, init?: RequestInit): Promise<T> {
  if (shouldUseMock()) {
    return resolveMockPath(path) as T
  }

  const response = await fetch(apiUrl(path), {
    ...init,
    method: "GET",
    headers: {
      Accept: "application/json",
      ...init?.headers
    }
  })

  return parseJsonResponse<T>(response)
}

async function parseJsonResponse<T>(response: Response): Promise<T> {
  const requestId = response.headers.get("x-request-id") ?? undefined
  const contentType = response.headers.get("content-type") ?? ""
  const payload = contentType.includes("application/json") ? await response.json() : await response.text()

  if (!response.ok) {
    const message =
      typeof payload === "object" && payload && "message" in payload ? String(payload.message) : response.statusText
    throw new ApiRequestError(
      {
        code: `http_${response.status}`,
        message,
        detail: payload,
        requestId
      },
      response.status
    )
  }

  return payload as T
}

function apiUrl(path: string): string {
  if (path.startsWith("http://") || path.startsWith("https://")) return path
  const baseUrl = process.env.NEXT_PUBLIC_NEWSROOM_API_BASE_URL ?? DEFAULT_API_BASE_URL
  const suffix = path.startsWith("/") ? path : `/${path}`
  return `${baseUrl.replace(/\/$/, "")}${suffix}`
}

function shouldUseMock(): boolean {
  return process.env.NEXT_PUBLIC_NEWSROOM_USE_MOCKS !== "false"
}
