import { notFound } from "next/navigation"
import { HumanReviewDetailPage } from "@/features/studio/review/components/human-review-detail-page"
import { getReviewItemDetail } from "@/features/studio/review/lib/human-review-adapter"

export default async function StudioReviewDetailRoute({ params }: { params: { approvalId: string } }) {
  const detail = await getReviewItemDetail(params.approvalId)
  if (!detail) notFound()
  return <HumanReviewDetailPage detail={detail} />
}
