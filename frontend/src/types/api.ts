import type { StudioApiError } from "@/types/studio"

export type ApiEnvelope<T> = {
  success: boolean
  data?: T
  error?: ApiEnvelopeError
  request_id?: string
  requestId?: string
  schema_version?: string
  schemaVersion?: string
}

export type ApiEnvelopeError = {
  code: string
  message: string
  details?: Record<string, unknown>
  retryable?: boolean
  user_action_required?: boolean
  request_id?: string
}

export type ApiResult<T> =
  | {
      ok: true
      data: T
      requestId?: string
      schemaVersion?: string
      raw: unknown
    }
  | {
      ok: false
      error: StudioApiError
      requestId?: string
      schemaVersion?: string
      raw: unknown
    }
