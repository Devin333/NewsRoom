import Link from "next/link"
import { EmptyState } from "@/components/common/empty-state"
import { ScoreMeter } from "@/components/common/score-meter"
import { AgentRunStatusBadge } from "@/features/studio/runs/components/agent-run-status-badge"
import { formatDuration, shortRunId } from "@/features/studio/runs/lib/run-format"
import { StudioTableFrame } from "@/features/studio/shared/components/studio-dashboard"
import { cn } from "@/lib/utils"
import { formatDateTime } from "@/lib/format"
import type { StudioRunListItem } from "@/types/agent"

export function RunListTable({ runs }: { runs: StudioRunListItem[] }) {
  if (!runs.length) {
    return <EmptyState title="No runs found" description="Adjust the filters or wait for the next workflow run." />
  }

  return (
    <StudioTableFrame>
      <div className="overflow-x-auto">
      <table className="w-full min-w-[1180px] border-collapse text-left text-sm">
        <thead className="border-b border-border bg-secondary/80 text-xs uppercase text-muted-foreground">
          <tr>
            <th className="px-4 py-3 font-medium">Run ID</th>
            <th className="px-4 py-3 font-medium">Workflow</th>
            <th className="px-4 py-3 font-medium">Profile</th>
            <th className="px-4 py-3 font-medium">Status</th>
            <th className="px-4 py-3 font-medium">Started</th>
            <th className="px-4 py-3 font-medium">Duration</th>
            <th className="px-4 py-3 font-medium">Steps</th>
            <th className="px-4 py-3 font-medium">Events</th>
            <th className="px-4 py-3 font-medium">Artifacts</th>
            <th className="px-4 py-3 font-medium">Quality</th>
            <th className="px-4 py-3 font-medium">Errors</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr
              key={run.id}
              className={cn(
                "border-b border-border/70 last:border-b-0 hover:bg-secondary/40",
                run.status === "failed" && "bg-danger/5",
                (run.status === "blocked" || run.status === "waiting_for_human") && "bg-warning/5"
              )}
            >
              <td className="px-4 py-3">
                <Link className="font-mono text-xs font-medium text-accent hover:underline" href={`/studio/runs/${encodeURIComponent(run.id)}`}>
                  {shortRunId(run.id)}
                </Link>
                {run.dataState === "fallback" ? <p className="mt-1 text-xs text-warning">fallback</p> : null}
              </td>
              <td className="px-4 py-3">
                <p className="font-medium text-foreground">{run.workflowName ?? run.workflowId ?? run.agentName}</p>
                {run.workflowVersion ? <p className="mt-1 text-xs text-muted-foreground">{run.workflowVersion}</p> : null}
              </td>
              <td className="px-4 py-3 text-muted-foreground">{run.profile}</td>
              <td className="px-4 py-3"><AgentRunStatusBadge status={run.status} /></td>
              <td className="px-4 py-3 text-muted-foreground">{formatDateTime(run.startedAt)}</td>
              <td className="px-4 py-3 text-muted-foreground">{formatDuration(run.durationMs)}</td>
              <td className="px-4 py-3 text-muted-foreground">{run.stepCount ?? 0}</td>
              <td className="px-4 py-3 text-muted-foreground">{run.eventCount ?? 0}</td>
              <td className="px-4 py-3 text-muted-foreground">{run.artifactCount}</td>
              <td className="w-36 px-4 py-3"><ScoreMeter value={run.qualityScore ?? 0} /></td>
              <td className={run.errorCount > 0 ? "px-4 py-3 font-semibold text-danger" : "px-4 py-3 text-muted-foreground"}>{run.errorCount}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </StudioTableFrame>
  )
}
