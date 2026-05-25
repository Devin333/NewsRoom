"use server"

import { requestReportReview } from "@/features/studio/quality/api/quality-gate-api"
import type { StudioRequestReviewPayload } from "@/types/quality"

export async function requestQualityReportReview(reportId: string, payload: StudioRequestReviewPayload) {
  return requestReportReview(reportId, payload)
}
