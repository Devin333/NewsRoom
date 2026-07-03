import { StudioHomePageClient } from "@/app/studio/studio-page-client"
import { fetchRunCenterList } from "@/features/studio/runs/api/run-center-api"
import { adaptRunList, buildStudioOverview } from "@/features/studio/runs/lib/run-center-adapter"

export default async function StudioPage() {
  const { runs, notices } = adaptRunList(await fetchRunCenterList())
  const overview = buildStudioOverview(runs)
  return <StudioHomePageClient overview={overview} notices={notices} />
}
