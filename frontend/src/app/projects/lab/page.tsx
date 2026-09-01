import { Suspense } from "react"
import { LabWorkspaceSkeleton, ProjectsProductPage } from "@/features/projects/components/projects-product-page"

export const dynamic = "force-dynamic"

export default function ProjectsLabPage() {
  return (
    <Suspense fallback={<LabWorkspaceSkeleton />}>
      <ProjectsProductPage route="lab" />
    </Suspense>
  )
}
