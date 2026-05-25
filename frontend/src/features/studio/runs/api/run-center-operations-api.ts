import { apiPost, ApiRequestError } from "@/lib/api/client"
import type { RunOperationPayload, RunOperationResult, RunOperationType } from "@/types/agent"

type ApiEnvelope<T> = {
  success?: boolean
  data?: T | null
  error?: {
    code?: string
    message?: string
    detail?: unknown
    details?: unknown
    requestId?: string
    request_id?: string | null
  } | null
  request_id?: string | null
}

export async function postRunOperation(
  runId: string,
  operation: RunOperationType,
  payload: RunOperationPayload
): Promise<RunOperationResult> {
  const encodedRunId = encodeURIComponent(decodeURIComponent(runId))
  const pathByOperation: Record<RunOperationType, string> = {
    cancel: `/api/v1/runs/${encodedRunId}/operations/cancel`,
    "rerun-from-step": `/api/v1/runs/${encodedRunId}/operations/rerun-from-step`,
    "skip-step": `/api/v1/runs/${encodedRunId}/operations/skip-step`,
    "mark-blocked-resolved": `/api/v1/runs/${encodedRunId}/operations/mark-blocked-resolved`
  }

  try {
    const response = await apiPost<ApiEnvelope<Record<string, unknown>> | Record<string, unknown>>(
      pathByOperation[operation],
      operationPayload(operation, payload)
    )
    const data = unwrapApiEnvelope(response)
    return {
      ok: true,
      operationType: readString(data.operation_type) ?? operation,
      status: readString(data.status),
      message: readString(data.message),
      raw: data
    }
  } catch (error) {
    if (error instanceof ApiRequestError) {
      return {
        ok: false,
        status: error.code,
        message: error.message,
        requestId: error.requestId,
        raw: error.detail
      }
    }
    return {
      ok: false,
      status: "request_failed",
      message: error instanceof Error ? error.message : "Operation failed"
    }
  }
}

function operationPayload(operation: RunOperationType, payload: RunOperationPayload): Record<string, unknown> {
  const base: Record<string, unknown> = {
    reason: payload.reason,
    metadata: payload.metadata ?? { source: "studio-run-center" }
  }
  if (payload.actorId) base.actor_id = payload.actorId

  if (operation === "rerun-from-step" || operation === "skip-step") {
    base.step_id = payload.stepId
  }

  if (operation === "mark-blocked-resolved") {
    base.resolved_by = payload.resolvedBy ?? payload.actorId
    base.resolution_type = payload.resolutionType ?? "manual"
  }

  return base
}

function unwrapApiEnvelope<T extends Record<string, unknown>>(response: ApiEnvelope<T> | T): T {
  if (isApiEnvelope<T>(response)) {
    const error = response.error
    if (response.success === false) {
      throw new ApiRequestError(
        {
          code: error?.code ?? "api_error",
          message: error?.message ?? "Operation failed",
          details: error?.detail ?? error?.details,
          requestId: error?.requestId ?? error?.request_id ?? response.request_id ?? undefined
        },
        undefined
      )
    }
    return (response.data ?? {}) as T
  }
  return response as T
}

function isApiEnvelope<T>(response: ApiEnvelope<T> | T): response is ApiEnvelope<T> {
  return Boolean(response && typeof response === "object" && "success" in response)
}

function readString(value: unknown): string | undefined {
  return typeof value === "string" && value.length ? value : undefined
}
