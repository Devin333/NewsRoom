import { normalizeApiError } from "@/lib/api/api-errors"
import { unwrapApiEnvelope } from "@/lib/api/api-envelope"
import { apiGet, apiPost } from "@/lib/api/client"
import type { ApiResult } from "@/types/api"

export async function newsroomApiGet<T>(path: string, init?: RequestInit): Promise<ApiResult<T>> {
  try {
    return unwrapApiEnvelope<T>(await apiGet<unknown>(path, init))
  } catch (error) {
    return apiErrorResult<T>(error)
  }
}

export async function newsroomApiPost<T>(
  path: string,
  body?: unknown,
  init?: RequestInit
): Promise<ApiResult<T>> {
  try {
    return unwrapApiEnvelope<T>(await apiPost<unknown>(path, body, init))
  } catch (error) {
    return apiErrorResult<T>(error)
  }
}

function apiErrorResult<T>(error: unknown): ApiResult<T> {
  return {
    ok: false,
    error: normalizeApiError(error),
    raw: error
  }
}
