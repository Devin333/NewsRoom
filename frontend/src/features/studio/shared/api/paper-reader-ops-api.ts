import { apiGet, apiPost } from "@/lib/api/client"
import type { Locale, PaperAISummary } from "@/lib/papers/types"
import type {
  PaperIngestOpsState,
  PaperIngestTriggerResult,
  PaperReaderOpsStats,
  PaperVisualCompileBackfillTriggerResult,
} from "@/types/studio"

type ApiEnvelope<T> = {
  success: boolean
  data?: T | null
  error?: {
    code: string
    message: string
    requestId?: string
    request_id?: string | null
  } | null
  request_id?: string | null
}

export async function fetchPaperReaderOpsStats(windowHours = 24): Promise<PaperReaderOpsStats> {
  const envelope = await apiGet<ApiEnvelope<{ stats: PaperReaderOpsStats }>>(
    `/api/papers/ops/stats?windowHours=${encodeURIComponent(String(windowHours))}`
  )
  if (envelope.success && envelope.data?.stats) {
    return envelope.data.stats
  }
  throw new Error(envelope.error?.message ?? "Paper Reader ops stats unavailable")
}

export async function fetchPaperIngestOpsState(limit = 20): Promise<PaperIngestOpsState> {
  const envelope = await apiGet<ApiEnvelope<{ ingest: PaperIngestOpsState }>>(
    `/api/papers/ops/ingest?limit=${encodeURIComponent(String(limit))}`
  )
  if (envelope.success && envelope.data?.ingest) {
    return envelope.data.ingest
  }
  throw new Error(envelope.error?.message ?? "Paper ingest ops unavailable")
}

export async function triggerPaperIngest({
  candidateLimit,
  minGithubStars,
}: {
  candidateLimit?: number
  minGithubStars?: number
}): Promise<PaperIngestTriggerResult> {
  const envelope = await apiPost<ApiEnvelope<{ enqueued: PaperIngestTriggerResult }>>(
    "/api/papers/ops/ingest",
    {
      candidateLimit,
      minGithubStars,
    }
  )
  if (envelope.success && envelope.data?.enqueued) {
    return envelope.data.enqueued
  }
  throw new Error(envelope.error?.message ?? "Paper ingest trigger failed")
}

export async function triggerPaperVisualCompileBackfill({
  limit,
  force,
}: {
  limit?: number
  force?: boolean
}): Promise<PaperVisualCompileBackfillTriggerResult> {
  const envelope = await apiPost<ApiEnvelope<{ enqueued: PaperVisualCompileBackfillTriggerResult }>>(
    "/api/papers/ops/visual-compile",
    {
      limit,
      force,
    }
  )
  if (envelope.success && envelope.data?.enqueued) {
    return envelope.data.enqueued
  }
  throw new Error(envelope.error?.message ?? "Paper Reader compile backfill trigger failed")
}

export async function refreshPaperReaderSummary({
  paperId,
  locale,
  reason,
}: {
  paperId: string
  locale: Locale
  reason: string
}): Promise<PaperAISummary> {
  const envelope = await apiPost<ApiEnvelope<{ summary: PaperAISummary }>>(
    `/api/papers/${encodeURIComponent(paperId)}/summary?locale=${locale}&refresh=true`,
    { reason }
  )
  if (envelope.success && envelope.data?.summary) {
    return envelope.data.summary
  }
  throw new Error(envelope.error?.message ?? "Paper summary refresh failed")
}
