import { Suspense } from "react"
import { PageSkeleton } from "@/components/common/loading-skeleton"
import { ProjectLabSessionPage } from "@/features/projects/components/projects-detail-pages"

export const dynamic = "force-dynamic"

export default function ProjectsLabSessionRoute({ params }: { params: { sessionId: string } }) {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <ProjectLabSessionPage sessionId={params.sessionId} />
    </Suspense>
  )
}
