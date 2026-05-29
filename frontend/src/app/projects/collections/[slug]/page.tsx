import { Suspense } from "react"
import { PageSkeleton } from "@/components/common/loading-skeleton"
import { ProjectCollectionDetailPage } from "@/features/projects/components/projects-detail-pages"

export const dynamic = "force-dynamic"

export default function ProjectsCollectionDetailRoute({ params }: { params: { slug: string } }) {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <ProjectCollectionDetailPage slug={params.slug} />
    </Suspense>
  )
}
