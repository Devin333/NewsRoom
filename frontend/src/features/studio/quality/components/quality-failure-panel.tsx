import Link from "next/link"
import { AlertTriangle, Ban, ExternalLink } from "lucide-react"
import { EmptyState } from "@/components/common/empty-state"
import { Badge } from "@/components/ui/badge"
import { QualityStatusBadge } from "@/features/studio/quality/components/quality-check-table"
import { StudioPanel } from "@/features/studio/shared/components/studio-dashboard"
import type { StudioBlockedRun, StudioQualityReportSummary } from "@/types/quality"

export function RecentFailedReports({ reports }: { reports: StudioQualityReportSummary[] }) {
  return (
    <StudioPanel title="Recent failed reports" description="Reports blocked by failed checks or review requirements." contentClassName="space-y-3">
      {!reports.length ? (
        <EmptyState title="No failed reports" description="Quality Gate has no failed or review-required reports in the current window." />
      ) : (
        reports.map((report) => (
          <Link
            key={report.reportId}
            href={`/studio/quality/reports/${encodeURIComponent(report.reportId)}`}
            className="block rounded-md border border-border bg-background p-3 hover:bg-secondary/50"
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-foreground">{report.title}</p>
                <p className="mt-1 truncate font-mono text-xs text-muted-foreground">{report.reportId}</p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <QualityStatusBadge status={report.status} />
                <ExternalLink className="size-4 text-muted-foreground" />
              </div>
            </div>
            {report.failureReasons.length ? (
              <p className="mt-2 line-clamp-2 text-sm text-muted-foreground">{report.failureReasons[0]}</p>
            ) : null}
          </Link>
        ))
      )}
    </StudioPanel>
  )
}

export function BlockedRunPanel({ runs }: { runs: StudioBlockedRun[] }) {
  return (
    <StudioPanel title="Blocked runs" description="Runs that need intervention before downstream publishing." contentClassName="space-y-3">
      {!runs.length ? (
        <div className="rounded-md border border-success/30 bg-success/10 p-4">
          <div className="flex items-start gap-3">
            <Ban className="mt-0.5 size-5 text-success" />
            <div>
              <p className="text-sm font-medium text-success">No blocked runs</p>
              <p className="mt-1 text-sm text-muted-foreground">Catalog health did not return blocked run evidence.</p>
            </div>
          </div>
        </div>
      ) : (
        runs.map((run) => (
          <div key={run.runId} className="rounded-md border border-warning/30 bg-warning/10 p-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate font-mono text-sm font-medium text-foreground">{run.runId}</p>
                <p className="mt-1 text-sm text-muted-foreground">{run.summary}</p>
              </div>
              <AlertTriangle className="size-5 shrink-0 text-warning" />
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <QualityStatusBadge status={run.status} />
              {run.severity ? <Badge variant="warning">{run.severity}</Badge> : null}
              {run.latestEventCount !== undefined ? <Badge variant="muted">{run.latestEventCount} events</Badge> : null}
            </div>
          </div>
        ))
      )}
    </StudioPanel>
  )
}

export function FailureReasonPanel({ reasons }: { reasons: string[] }) {
  return (
    <StudioPanel title="Failure reasons">
      {!reasons.length ? (
        <p className="text-sm text-muted-foreground">No explicit failure reason was returned by the quality payload.</p>
      ) : (
        <ul className="space-y-2">
          {reasons.map((reason) => (
            <li key={reason} className="flex gap-2 rounded-md border border-danger/20 bg-danger/10 p-3 text-sm">
              <AlertTriangle className="mt-0.5 size-4 shrink-0 text-danger" />
              <span className="text-foreground">{reason}</span>
            </li>
          ))}
        </ul>
      )}
    </StudioPanel>
  )
}
