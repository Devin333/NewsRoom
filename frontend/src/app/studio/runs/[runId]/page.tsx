import { AgentRunDetailPage } from "@/features/studio/runs/components/agent-run-detail-page";
import { getStudioAgentRunDetail } from "@/features/studio/runs/lib/agent-run-adapter";

export default async function StudioRunDetailPage({ params }: { params: { runId: string } }) {
  const detail = await getStudioAgentRunDetail(params.runId);
  return <AgentRunDetailPage runId={params.runId} detail={detail} />;
}
