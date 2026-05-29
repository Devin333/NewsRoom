import { Suspense } from "react"
import { PageSkeleton } from "@/components/common/loading-skeleton"
import { ProjectCaseDetailPage } from "@/features/projects/components/projects-detail-pages"

export const dynamic = "force-dynamic"

export default function ProjectsCaseDetailRoute({ params }: { params: { caseId: string } }) {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <ProjectCaseDetailPage caseId={params.caseId} />
    </Suspense>
  )
}
