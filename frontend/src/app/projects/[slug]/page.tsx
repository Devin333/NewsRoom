import { notFound } from "next/navigation"
import { ProjectDetailPanel } from "@/features/projects/components/project-detail-panel"
import { getProjectDetail } from "@/lib/projects/data-source"

export const dynamic = "force-dynamic"

export default async function ProjectDetailPage({ params }: { params: { slug: string } }) {
  const result = await getProjectDetail(params.slug)
  if (!result) {
    notFound()
  }
  return <ProjectDetailPanel project={result.project} />
}
