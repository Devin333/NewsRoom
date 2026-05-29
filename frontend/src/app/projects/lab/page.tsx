import { Suspense } from "react"
import { PageSkeleton } from "@/components/common/loading-skeleton"
import { ProjectsProductPage } from "@/features/projects/components/projects-product-page"

export const dynamic = "force-dynamic"

export default function ProjectsLabPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <ProjectsProductPage route="lab" />
    </Suspense>
  )
}
