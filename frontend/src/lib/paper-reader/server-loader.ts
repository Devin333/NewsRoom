import { safeApiGet, type SafeApiResult } from "@/lib/api/server"
import type { Paper } from "@/lib/papers/types"
import { getPaperById } from "@/lib/papers/real-data"
import type { PaperCompileStatusRecord, PaperDocumentResponse } from "@/lib/paper-reader/types"

type DocumentApiResult = SafeApiResult<PaperDocumentResponse>
type StatusApiResult = SafeApiResult<{ status: PaperCompileStatusRecord }>

const DOCUMENT_LOAD_TIMEOUT_MS = 2500
const STATUS_LOAD_TIMEOUT_MS = 1200
const REQUEST_TIMEOUT_CODE = "request_timeout"

export async function loadPaperDocumentPayload(paperRef: string): Promise<PaperDocumentResponse | null> {
  const firstDocument = await getDocumentPayload(paperRef)
  if (firstDocument.ok) {
    return publicDocumentPayload(firstDocument.data)
  }

  const paper = await getPaperById(paperRef)
  if (!paper) {
    return null
  }

  if (paper.id !== paperRef && firstDocument.errorCode !== REQUEST_TIMEOUT_CODE) {
    const resolvedDocument = await getDocumentPayload(paper.id)
    if (resolvedDocument.ok) {
      return publicDocumentPayload(resolvedDocument.data)
    }
  }

  const status = await getBestCompileStatus(paper.id, firstDocument)
  return {
    paper,
    status,
    document: null,
    manifest: null,
    ai: {
      summary: paper.aiSummary ?? null,
      signals: {
        abstractSnippet: paper.abstractSnippet,
        methodRefs: paper.methodRefs,
        taskRefs: paper.taskRefs,
        benchmarks: paper.benchmarks,
        implementations: paper.implementations,
      },
      diagnostics: status.diagnostics,
    },
  }
}

function publicDocumentPayload(payload: PaperDocumentResponse): PaperDocumentResponse | null {
  return payload.paper.isPublished === false ? null : payload
}

export async function loadPaperCompileStatus(paperRef: string): Promise<PaperCompileStatusRecord | null> {
  const paper = await getPaperById(paperRef)
  if (!paper) {
    return null
  }
  const status = await getCompileStatus(paper.id)
  if (status.ok) {
    return status.data.status
  }
  return fallbackCompileStatus(paper, status)
}

async function getDocumentPayload(paperId: string): Promise<DocumentApiResult> {
  return safeApiGetWithTimeout<PaperDocumentResponse>(
    `/api/v1/papers/${encodeURIComponent(paperId)}/document`,
    DOCUMENT_LOAD_TIMEOUT_MS,
    "Reader document request timed out before a compiled document became available.",
  )
}

async function getCompileStatus(paperId: string): Promise<StatusApiResult> {
  return safeApiGetWithTimeout<{ status: PaperCompileStatusRecord }>(
    `/api/v1/papers/${encodeURIComponent(paperId)}/compile-status`,
    STATUS_LOAD_TIMEOUT_MS,
    "Reader compile status request timed out.",
  )
}

async function safeApiGetWithTimeout<T>(
  path: string,
  timeoutMs: number,
  timeoutMessage: string,
): Promise<SafeApiResult<T>> {
  const controller = new AbortController()
  let timer: ReturnType<typeof setTimeout> | undefined
  const timeoutResult = new Promise<SafeApiResult<T>>((resolve) => {
    timer = setTimeout(() => {
      controller.abort()
      resolve({
        ok: false,
        errorCode: REQUEST_TIMEOUT_CODE,
        errorMessage: timeoutMessage,
      })
    }, timeoutMs)
  })

  try {
    return await Promise.race([
      safeApiGet<T>(path, { signal: controller.signal }),
      timeoutResult,
    ])
  } finally {
    if (timer) clearTimeout(timer)
  }
}

async function getBestCompileStatus(
  paperId: string,
  documentResult: Extract<DocumentApiResult, { ok: false }>,
): Promise<PaperCompileStatusRecord> {
  const status = await getCompileStatus(paperId)
  if (status.ok) {
    return withDocumentDiagnostic(status.data.status, documentResult)
  }
  const paper = await getPaperById(paperId)
  if (!paper) {
    return fallbackCompileStatus({ id: paperId }, documentResult)
  }
  return fallbackCompileStatus(paper, documentResult)
}

function withDocumentDiagnostic(
  status: PaperCompileStatusRecord,
  documentResult: Extract<DocumentApiResult, { ok: false }>,
): PaperCompileStatusRecord {
  const diagnostics = [
    ...status.diagnostics,
    {
      severity: "warning" as const,
      code: documentResult.errorCode,
      message: documentResult.errorMessage,
    },
  ]
  if (status.status !== "compiled") {
    return {
      ...status,
      diagnostics,
    }
  }
  return {
    ...status,
    status: "queued",
    diagnostics,
  }
}

function fallbackCompileStatus(
  paper: Pick<Paper, "id">,
  result: Extract<DocumentApiResult | StatusApiResult, { ok: false }>,
): PaperCompileStatusRecord {
  return {
    paperId: paper.id,
    status: "queued",
    updatedAt: new Date().toISOString(),
    diagnostics: [
      {
        severity: "warning",
        code: result.errorCode,
        message: result.errorMessage || "compiled document is not available yet",
      },
    ],
  }
}
