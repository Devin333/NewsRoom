import type { ApiEnvelope, ApiEnvelopeError } from "@/types/api"

type MockApiOptions = {
  status?: number
  requestId?: string
  schemaVersion?: string
  headers?: HeadersInit
}

const jsonHeaders = {
  "content-type": "application/json"
}

export function mockApiSuccess<T>(data: T, options: MockApiOptions = {}): Response {
  return jsonResponse<ApiEnvelope<T>>(
    {
      success: true,
      data,
      request_id: options.requestId ?? "req-test-success",
      schema_version: options.schemaVersion ?? "studio-test-v1"
    },
    options.status ?? 200,
    options.headers
  )
}

export function mockApiError(error: ApiEnvelopeError, options: MockApiOptions = {}): Response {
  return jsonResponse<ApiEnvelope<never>>(
    {
      success: false,
      error,
      request_id: options.requestId ?? error.request_id ?? "req-test-error",
      schema_version: options.schemaVersion ?? "studio-test-v1"
    },
    options.status ?? 200,
    options.headers
  )
}

export function mockApiNetworkFailure(message = "Network failure"): Promise<Response> {
  return Promise.reject(new Error(message))
}

export function mockApiPartial<T extends Record<string, unknown>>(data: T): Response {
  return mockApiSuccess(
    {
      ...data,
      dataState: "partial",
      notices: ["Partial data returned by test mock API."]
    },
    { requestId: "req-test-partial" }
  )
}

export function mockApiEmpty(): Response {
  return mockApiSuccess(
    {
      items: [],
      total: 0,
      page: 1,
      pageSize: 20,
      hasNext: false,
      dataState: "ready",
      notices: ["Empty data returned by test mock API."]
    },
    { requestId: "req-test-empty" }
  )
}

function jsonResponse<T>(payload: T, status: number, headers?: HeadersInit): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      ...jsonHeaders,
      ...headers
    }
  })
}
