import { Suspense } from "react"
import { PageSkeleton } from "@/components/common/loading-skeleton"
import { ProjectRadarPage } from "@/features/projects/components/project-radar-page"

export const dynamic = "force-dynamic"

export default function ProjectsPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <ProjectRadarPage />
    </Suspense>
  )
}
