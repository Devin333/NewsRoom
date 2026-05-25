import { apiGet } from "@/lib/api/client"
import type { PaperPdfProxyStats } from "@/types/studio"

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

export async function fetchPaperPdfProxyStats(windowHours = 24): Promise<PaperPdfProxyStats> {
  const envelope = await apiGet<ApiEnvelope<{ stats: PaperPdfProxyStats }>>(
    `/api/papers/pdf/stats?windowHours=${encodeURIComponent(String(windowHours))}`
  )
  if (envelope.success && envelope.data?.stats) {
    return envelope.data.stats
  }
  throw new Error(envelope.error?.message ?? "PDF proxy stats unavailable")
}
