import { RunCenterPage } from "@/features/studio/runs/components/run-center-page"
import { fetchRunCenterList } from "@/features/studio/runs/api/run-center-api"
import { adaptRunList } from "@/features/studio/runs/lib/run-center-adapter"

export default async function StudioRunsPage() {
  const { runs, notices } = adaptRunList(await fetchRunCenterList())
  return <RunCenterPage runs={runs} notices={notices} />
}
