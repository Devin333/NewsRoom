import { EmptyState } from "@/components/common/empty-state"
import { SourceHealthBadge } from "@/components/common/source-health-badge"
import { StudioField, StudioFieldGrid, StudioPanel } from "@/features/studio/shared/components/studio-dashboard"
import { formatDateTime, formatDurationMs, formatNumber, titleCase } from "@/lib/format"
import type { Source } from "@/types/source"

export function SourceDetailPanel({ source }: { source?: Source }) {
  if (!source) {
    return <EmptyState title="No source selected" description="Select a source row to inspect recent runs, errors, and latest items." />
  }

  return (
    <section className="grid gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
      <StudioPanel
        title={source.name}
        description={source.id}
        actions={<SourceHealthBadge status={source.healthStatus} />}
      >
        <div className="space-y-4">
          <StudioFieldGrid className="xl:grid-cols-2">
            <StudioField label="Type" value={titleCase(source.type)} />
            <StudioField label="Enabled" value={source.enabled ? "Yes" : "No"} />
            <StudioField label="Last run" value={formatDateTime(source.lastRunAt)} />
            <StudioField label="Last success" value={formatDateTime(source.lastSuccessAt)} />
            <StudioField label="Collected 24h" value={formatNumber(source.collectedCount24h)} />
            <StudioField label="Avg latency" value={formatDurationMs(source.avgLatencyMs)} />
          </StudioFieldGrid>
          <div className="rounded-md border border-border bg-secondary/30 p-3 text-sm leading-6 text-muted-foreground">
            {source.configSummary ?? "No config summary returned."}
          </div>
        </div>
      </StudioPanel>

      <div className="space-y-4">
        <StudioPanel title="Recent run history" contentClassName="space-y-2">
          {(source.recentRuns ?? []).length ? (
            (source.recentRuns ?? []).map((run) => (
              <div key={run.id} className="rounded-md border border-border bg-background p-3 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium text-foreground">{run.id}</span>
                  <SourceHealthBadge status={run.status} />
                </div>
                <p className="mt-1 text-muted-foreground">
                  {formatDateTime(run.startedAt)} | {formatNumber(run.collectedCount)} items | {formatDurationMs(run.latencyMs)}
                </p>
                {run.errorMessage ? <p className="mt-1 text-danger">{run.errorMessage}</p> : null}
              </div>
            ))
          ) : (
            <p className="text-sm text-muted-foreground">No recent source run history.</p>
          )}
        </StudioPanel>

        <StudioPanel title="Errors and latest items">
          {source.errorSummary?.length ? (
            <ul className="mb-4 space-y-1 text-sm text-danger">
              {source.errorSummary.map((error) => <li key={error}>{error}</li>)}
            </ul>
          ) : (
            <p className="mb-4 text-sm text-muted-foreground">No recent error summary.</p>
          )}
          <div className="space-y-2">
            {(source.latestItems ?? []).map((item) => (
              <div key={item.id} className="rounded-md border border-border bg-background p-3 text-sm">
                <p className="font-medium text-foreground">{item.title}</p>
                <p className="mt-1 text-muted-foreground">{formatDateTime(item.capturedAt)}</p>
              </div>
            ))}
            {!source.latestItems?.length ? <p className="text-sm text-muted-foreground">No latest item preview.</p> : null}
          </div>
        </StudioPanel>
      </div>
    </section>
  )
}
