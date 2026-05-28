import { safeApiGet, type SafeApiResult } from "@/lib/api/server"
import type { Paper } from "@/lib/papers/types"
import { getPaperById } from "@/lib/papers/real-data"
import type { PaperCompileStatusRecord, PaperDocumentResponse } from "@/lib/paper-reader/types"

type DocumentApiResult = SafeApiResult<PaperDocumentResponse>
type StatusApiResult = SafeApiResult<{ status: PaperCompileStatusRecord }>

export async function loadPaperDocumentPayload(paperRef: string): Promise<PaperDocumentResponse | null> {
  const firstDocument = await getDocumentPayload(paperRef)
  if (firstDocument.ok) {
    return firstDocument.data
  }

  const paper = await getPaperById(paperRef)
  if (!paper) {
    return null
  }

  if (paper.id !== paperRef) {
    const resolvedDocument = await getDocumentPayload(paper.id)
    if (resolvedDocument.ok) {
      return resolvedDocument.data
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
  return safeApiGet<PaperDocumentResponse>(`/api/v1/papers/${encodeURIComponent(paperId)}/document`)
}

async function getCompileStatus(paperId: string): Promise<StatusApiResult> {
  return safeApiGet<{ status: PaperCompileStatusRecord }>(`/api/v1/papers/${encodeURIComponent(paperId)}/compile-status`)
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
  if (status.status !== "compiled") {
    return status
  }
  return {
    ...status,
    status: "queued",
    diagnostics: [
      ...status.diagnostics,
      {
        severity: "warning",
        code: documentResult.errorCode,
        message: documentResult.errorMessage,
      },
    ],
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
