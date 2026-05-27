import { apiGet, apiPost } from "@/lib/api/client"
import type {
  PaperCompileStatusRecord,
  PaperCompileTriggerResponse,
  PaperDocumentResponse,
  PaperSourceRegion,
} from "@/lib/paper-reader/types"

type ApiEnvelope<T> = {
  success: boolean
  data?: T | null
  error?: {
    code: string
    message: string
    details?: unknown
    detail?: unknown
    retryable?: boolean
  } | null
}

export class PaperReaderApiError extends Error {
  code: string
  detail?: unknown
  retryable?: boolean

  constructor(message: string, code = "paper_reader_api_error", detail?: unknown, retryable?: boolean) {
    super(message)
    this.name = "PaperReaderApiError"
    this.code = code
    this.detail = detail
    this.retryable = retryable
  }
}

export async function fetchPaperDocument(paperId: string, init?: RequestInit): Promise<PaperDocumentResponse> {
  const envelope = await apiGet<ApiEnvelope<PaperDocumentResponse>>(
    `/api/papers/${encodeURIComponent(paperId)}/document`,
    init,
  )
  return unwrapEnvelope(envelope)
}

export async function fetchPaperCompileStatus(paperId: string, init?: RequestInit): Promise<PaperCompileStatusRecord> {
  const envelope = await apiGet<ApiEnvelope<{ status: PaperCompileStatusRecord }>>(
    `/api/papers/${encodeURIComponent(paperId)}/compile-status`,
    init,
  )
  return unwrapEnvelope(envelope).status
}

export async function triggerPaperCompile(
  paperId: string,
  options: { force?: boolean; runId?: string } = {},
  init?: RequestInit,
): Promise<PaperCompileTriggerResponse> {
  const envelope = await apiPost<ApiEnvelope<PaperCompileTriggerResponse>>(
    `/api/papers/${encodeURIComponent(paperId)}/compile`,
    options,
    init,
  )
  return unwrapEnvelope(envelope)
}

export function paperAssetUrl(paperId: string, assetId: string) {
  return `/api/papers/${encodeURIComponent(paperId)}/assets/${encodeURIComponent(assetId)}`
}

export function paperSourcePreviewUrl(paperId: string, source: PaperSourceRegion) {
  const bbox = encodeURIComponent(JSON.stringify(source.bbox))
  return `/api/papers/${encodeURIComponent(paperId)}/source-preview?page=${source.pageNumber}&bbox=${bbox}`
}

function unwrapEnvelope<T>(envelope: ApiEnvelope<T>): T {
  if (envelope.success && envelope.data) {
    return envelope.data
  }
  const error = envelope.error
  throw new PaperReaderApiError(
    error?.message ?? "Paper reader API request failed",
    error?.code,
    error?.detail ?? error?.details,
    error?.retryable,
  )
}
