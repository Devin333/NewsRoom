import { Suspense } from "react"
import { PageSkeleton } from "@/components/common/loading-skeleton"
import { ProjectV1DetailPage } from "@/features/projects/components/projects-detail-pages"

export const dynamic = "force-dynamic"

export default function ProjectDetailPage({ params }: { params: { slug: string } }) {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <ProjectV1DetailPage projectId={params.slug} />
    </Suspense>
  )
}
