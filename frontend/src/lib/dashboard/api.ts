import type { DashboardOverview } from "@/types/dashboard"

type DashboardOverviewEnvelope = {
  success: boolean
  data?: DashboardOverview | null
  error?: {
    code?: string
    message?: string
    detail?: unknown
    details?: unknown
  } | null
}

export class DashboardApiError extends Error {
  code: string
  detail?: unknown
  status?: number

  constructor(message: string, code = "dashboard_api_error", detail?: unknown, status?: number) {
    super(message)
    this.name = "DashboardApiError"
    this.code = code
    this.detail = detail
    this.status = status
  }
}

export async function fetchDashboardOverview(init?: RequestInit): Promise<DashboardOverview> {
  const response = await fetch("/api/dashboard/overview", {
    ...init,
    method: "GET",
    headers: {
      Accept: "application/json",
      ...init?.headers
    },
    cache: "no-store"
  })

  const envelope = await parseEnvelope(response)
  if (!response.ok || !envelope.success || !envelope.data) {
    const error = envelope.error
    throw new DashboardApiError(
      error?.message ?? response.statusText ?? "Dashboard overview request failed",
      error?.code ?? `http_${response.status}`,
      error?.detail ?? error?.details ?? envelope,
      response.status
    )
  }

  return envelope.data
}

async function parseEnvelope(response: Response): Promise<DashboardOverviewEnvelope> {
  const contentType = response.headers.get("content-type") ?? ""
  if (!contentType.includes("application/json")) {
    return {
      success: false,
      data: null,
      error: {
        code: "invalid_response",
        message: await response.text()
      }
    }
  }
  return (await response.json()) as DashboardOverviewEnvelope
}
