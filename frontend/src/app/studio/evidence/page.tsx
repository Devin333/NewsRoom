import { EvidenceCenterPage } from "@/features/studio/evidence/components/evidence-center-page"
import { getEvidenceOverview } from "@/features/studio/evidence/api/evidence-api"

export default async function StudioEvidencePage() {
  const overview = await getEvidenceOverview()
  return <EvidenceCenterPage overview={overview} />
}
