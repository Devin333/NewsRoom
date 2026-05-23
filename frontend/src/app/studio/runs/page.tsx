import { AgentRunListPage } from "@/features/studio/runs/components/agent-run-list-page"
import { getStudioAgentRuns } from "@/features/studio/runs/lib/agent-run-adapter"

export default async function StudioRunsPage() {
  const { runs, notices } = await getStudioAgentRuns()
  return <AgentRunListPage runs={runs} notices={notices} />
}
