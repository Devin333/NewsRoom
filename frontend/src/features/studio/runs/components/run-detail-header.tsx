import { Badge } from "@/components/common/badge"
import { ScoreMeter } from "@/components/common/score-meter"
import { AgentRunStatusBadge } from "@/features/studio/runs/components/agent-run-status-badge"
import { formatDuration, shortRunId } from "@/features/studio/runs/lib/run-format"
import { formatDateTime } from "@/lib/format"
import type { AgentRun } from "@/types/agent"

export function RunDetailHeader({ run }: { run: AgentRun }) {
  return (
    <header className="rounded-lg border border-border bg-card p-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <AgentRunStatusBadge status={run.status} />
            <Badge tone="accent">{run.agentName}</Badge>
            <Badge tone="neutral">{run.profile}</Badge>
          </div>
          <div>
            <h1 className="break-all text-2xl font-semibold tracking-normal text-foreground">{run.workflowName ?? run.agentName}</h1>
            <p className="mt-1 font-mono text-xs text-muted-foreground">{shortRunId(run.id)}</p>
          </div>
        </div>
        <div className="w-full max-w-xs">
          <ScoreMeter label="质量" value={run.qualityScore ?? 0} />
        </div>
      </div>

      <dl className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Metric label="开始" value={formatDateTime(run.startedAt)} />
        <Metric label="完成" value={formatDateTime(run.finishedAt)} />
        <Metric label="耗时" value={formatDuration(run.durationMs)} />
        <Metric label="输入 / 输出" value={`${run.inputCount} / ${run.outputCount}`} />
        <Metric label="步骤 / 产物" value={`${run.stepCount ?? 0} / ${run.artifactCount}`} />
      </dl>
    </header>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border bg-secondary/40 p-3">
      <dt className="text-xs uppercase tracking-normal text-muted-foreground">{label}</dt>
      <dd className="mt-1 truncate text-sm font-medium text-foreground">{value}</dd>
    </div>
  )
}
