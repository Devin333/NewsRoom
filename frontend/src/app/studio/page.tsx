import { StudioOverviewDashboard } from "@/features/studio/components/studio-overview-dashboard";
import { getStudioOverview } from "@/features/studio/runs/lib/agent-run-adapter";

export default async function StudioPage() {
  const overview = await getStudioOverview();
  return <StudioOverviewDashboard overview={overview} />;
}
