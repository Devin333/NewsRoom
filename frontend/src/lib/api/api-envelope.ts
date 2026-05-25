import { normalizeApiError } from "@/lib/api/api-errors"
import type { ApiEnvelope, ApiResult } from "@/types/api"

export function unwrapApiEnvelope<T>(payload: unknown): ApiResult<T> {
  if (!isApiEnvelopePayload(payload)) {
    return {
      ok: true,
      data: payload as T,
      raw: payload
    }
  }

  const requestId = payload.requestId ?? payload.request_id
  const schemaVersion = payload.schemaVersion ?? payload.schema_version

  if (payload.success === false) {
    const normalizedError = normalizeApiError(payload.error ?? payload)

    return {
      ok: false,
      error: {
        ...normalizedError,
        requestId: normalizedError.requestId ?? requestId
      },
      requestId,
      schemaVersion,
      raw: payload
    }
  }

  return {
    ok: true,
    data: payload.data as T,
    requestId,
    schemaVersion,
    raw: payload
  }
}

export function isApiEnvelopePayload<T = unknown>(payload: unknown): payload is ApiEnvelope<T> {
  return (
    typeof payload === "object" &&
    payload !== null &&
    "success" in payload &&
    typeof (payload as { success?: unknown }).success === "boolean"
  )
}
