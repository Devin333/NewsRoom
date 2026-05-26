import { Suspense } from "react"
import { PageSkeleton } from "@/components/common/loading-skeleton"
import { CommunityPageClient } from "@/app/community/community-page-client"

export default function CommunityPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <CommunityPageClient />
    </Suspense>
  )
}
