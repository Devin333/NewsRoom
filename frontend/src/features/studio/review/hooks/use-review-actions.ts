"use client"

import { useRouter } from "next/navigation"
import { submitReviewAction } from "@/features/studio/review/api/human-review-api"
import type { ReviewActionRequest, ReviewActionResult } from "@/types/review"

export function useReviewActions() {
  const router = useRouter()

  async function submitAction(request: ReviewActionRequest): Promise<ReviewActionResult> {
    const result = await submitReviewAction(request)
    if (result.ok) router.refresh()
    return result
  }

  return { submitAction }
}
