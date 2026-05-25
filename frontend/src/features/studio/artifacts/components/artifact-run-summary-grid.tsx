import { Archive, Clock, FileJson2, ListTree, Workflow } from "lucide-react"
import { StudioMetricCard, StudioMetricGrid } from "@/features/studio/shared/components/studio-dashboard"
import { formatDateTime, formatNumber } from "@/lib/format"
import type { StudioArtifactRunSummary } from "@/types/artifact"

export function ArtifactRunSummaryGrid({ run }: { run: StudioArtifactRunSummary }) {
  return (
    <StudioMetricGrid className="xl:grid-cols-5 2xl:grid-cols-5">
      <StudioMetricCard label="Artifacts" value={formatNumber(run.artifactCount)} detail={run.artifactStatus} icon={Archive} tone={run.artifactStatus === "ready" ? "success" : "warning"} />
      <StudioMetricCard label="Events" value={formatNumber(run.eventCount)} detail="Runtime events" icon={Workflow} />
      <StudioMetricCard label="Step results" value={formatNumber(run.stepResultCount)} detail="Step output records" icon={ListTree} />
      <StudioMetricCard label="Status" value={run.status} detail={run.profile ?? "unknown profile"} icon={FileJson2} />
      <StudioMetricCard label="Started" value={<span className="text-sm">{formatDateTime(run.startedAt)}</span>} detail="Run start time" icon={Clock} />
    </StudioMetricGrid>
  )
}
