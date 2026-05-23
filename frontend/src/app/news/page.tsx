import { Suspense } from "react"
import { PageSkeleton } from "@/components/common/loading-skeleton"
import { NewsPageClient } from "@/app/news/news-page-client"

export default function NewsPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <NewsPageClient />
    </Suspense>
  )
}
