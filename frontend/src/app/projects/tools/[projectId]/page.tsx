import { Suspense } from "react"
import { PageSkeleton } from "@/components/common/loading-skeleton"
import { ProjectToolDetailPage } from "@/features/projects/components/projects-detail-pages"

export const dynamic = "force-dynamic"

export default function ProjectsToolDetailRoute({ params }: { params: { projectId: string } }) {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <ProjectToolDetailPage projectId={params.projectId} />
    </Suspense>
  )
}
