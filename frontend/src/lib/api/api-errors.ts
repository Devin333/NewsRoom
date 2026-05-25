import type { StudioApiError } from "@/types/studio"

const DEFAULT_ERROR_CODE = "request_failed"
const DEFAULT_ERROR_MESSAGE = "API request failed"

export function normalizeApiError(error: unknown): StudioApiError {
  if (typeof error === "string") {
    return {
      code: DEFAULT_ERROR_CODE,
      message: error || DEFAULT_ERROR_MESSAGE
    }
  }

  if (error instanceof Error) {
    const record = error as Error & Record<string, unknown>
    return {
      code: readString(record.code) ?? DEFAULT_ERROR_CODE,
      message: error.message || DEFAULT_ERROR_MESSAGE,
      details: record.detail ?? record.details,
      retryable: readBoolean(record.retryable),
      userActionRequired: readBoolean(record.userActionRequired) ?? readBoolean(record.user_action_required),
      requestId: readString(record.requestId) ?? readString(record.request_id),
      status: readNumber(record.status)
    }
  }

  if (!isRecord(error)) {
    return {
      code: DEFAULT_ERROR_CODE,
      message: DEFAULT_ERROR_MESSAGE,
      details: error
    }
  }

  if (error.success === false) {
    const nested = normalizeApiError(error.error ?? error)
    const requestId =
      nested.requestId ??
      readString(error.requestId) ??
      readString(error.request_id) ??
      (isRecord(error.error) ? readString(error.error.requestId) ?? readString(error.error.request_id) : undefined)

    return {
      ...nested,
      requestId
    }
  }

  const nestedError = isRecord(error.error) ? error.error : undefined
  const source = nestedError ?? error

  return {
    code: readString(source.code) ?? readString(error.code) ?? DEFAULT_ERROR_CODE,
    message:
      readString(source.message) ??
      readString(source.error_message) ??
      readString(error.message) ??
      DEFAULT_ERROR_MESSAGE,
    details: source.detail ?? source.details ?? error.detail ?? error.details,
    retryable: readBoolean(source.retryable) ?? readBoolean(error.retryable),
    userActionRequired:
      readBoolean(source.userActionRequired) ??
      readBoolean(source.user_action_required) ??
      readBoolean(error.userActionRequired) ??
      readBoolean(error.user_action_required),
    requestId:
      readString(source.requestId) ??
      readString(source.request_id) ??
      readString(error.requestId) ??
      readString(error.request_id),
    status: readNumber(source.status) ?? readNumber(error.status)
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null
}

function readString(value: unknown): string | undefined {
  return typeof value === "string" && value.length ? value : undefined
}

function readBoolean(value: unknown): boolean | undefined {
  return typeof value === "boolean" ? value : undefined
}

function readNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined
}
