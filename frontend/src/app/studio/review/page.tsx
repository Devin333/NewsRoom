import { HumanReviewPage } from "@/features/studio/review/components/human-review-page"
import { getReviewQueue } from "@/features/studio/review/lib/human-review-adapter"

export default async function StudioReviewPage() {
  const queue = await getReviewQueue()
  return <HumanReviewPage queue={queue} />
}
