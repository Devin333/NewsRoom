import { RunEvidencePage } from "@/features/studio/evidence/components/run-evidence-page"
import { getRunEvidenceDetail } from "@/features/studio/evidence/api/evidence-api"

export default async function StudioEvidenceRunPage({
  params,
  searchParams
}: {
  params: { runId: string }
  searchParams?: { reportId?: string }
}) {
  const detail = await getRunEvidenceDetail(params.runId, searchParams?.reportId)
  return <RunEvidencePage detail={detail} />
}
