import Link from "next/link"
import { CheckCircle2, CircleHelp, FileWarning, Network, XCircle } from "lucide-react"
import { Badge } from "@/components/common/badge"
import {
  StudioMetricCard,
  StudioMetricGrid,
  StudioNotice,
  StudioPageHeader,
  StudioPanel
} from "@/features/studio/shared/components/studio-dashboard"
import type { StudioEvidenceOverview, StudioEvidenceRunSummary } from "@/types/evidence"

export function EvidenceCenterPage({ overview }: { overview: StudioEvidenceOverview }) {
  return (
    <main className="space-y-6">
      <StudioPageHeader
        eyebrow="Business"
        title="Evidence Center"
        description="Audit claim support, source grounding, citation failures, and quality lineage for recent NewsRoom runs."
      />
      <NoticeList notices={overview.notices} tone={overview.dataState === "ready" ? "success" : "warning"} />
      <StudioMetricGrid className="xl:grid-cols-5 2xl:grid-cols-5">
        <StudioMetricCard label="Claims" value={overview.totals.total} detail="Total claims" icon={Network} tone="accent" />
        <StudioMetricCard label="Accepted" value={overview.totals.accepted} detail="Supported claims" icon={CheckCircle2} tone="success" />
        <StudioMetricCard label="Rejected" value={overview.totals.rejected} detail="Rejected claims" icon={XCircle} tone="danger" />
        <StudioMetricCard label="Uncertain" value={overview.totals.uncertain} detail="Needs review" icon={CircleHelp} tone="warning" />
        <StudioMetricCard label="Unsupported" value={overview.totals.unsupported} detail="Support missing" icon={FileWarning} tone="info" />
      </StudioMetricGrid>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <StudioPanel title="Recent evidence health" description="Runs with claim support and quality lineage data." contentClassName="space-y-3">
          {overview.runs.length ? overview.runs.map((run) => <RunSummaryRow key={run.runId} run={run} />) : <p className="text-sm text-muted-foreground">No recent evidence runs.</p>}
        </StudioPanel>
        <StudioPanel title="Citation failures" description="Grouped citation and claim support failure categories." contentClassName="space-y-3">
          {overview.citationFailureCategories.length ? (
            overview.citationFailureCategories.map((category) => (
              <div key={category.code} className="rounded-md border border-border bg-background p-3">
                <div className="flex items-center justify-between gap-3">
                  <p className="font-medium text-foreground">{category.label ?? category.code}</p>
                  <Badge tone="warning">{category.count}</Badge>
                </div>
                {category.items.length ? <p className="mt-2 text-xs leading-5 text-muted-foreground">{category.items.slice(0, 2).join("; ")}</p> : null}
              </div>
            ))
          ) : (
            <p className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">No citation failure categories reported.</p>
          )}
        </StudioPanel>
      </section>
    </main>
  )
}

function RunSummaryRow({ run }: { run: StudioEvidenceRunSummary }) {
  const href = `/studio/evidence/runs/${encodeURIComponent(run.runId)}${run.reportId ? `?reportId=${encodeURIComponent(run.reportId)}` : ""}`
  return (
    <Link href={href} className="block rounded-md border border-border bg-background p-4 transition-colors hover:bg-secondary/40">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="break-words font-medium text-foreground">{run.workflowName ?? run.runId}</p>
          <p className="mt-1 break-words font-mono text-xs text-muted-foreground">{run.runId}</p>
          {run.reportId ? <p className="mt-1 break-words text-xs text-muted-foreground">Report {run.reportId}</p> : null}
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge tone={run.dataState === "ready" ? "success" : run.dataState === "fallback" ? "info" : "warning"}>{run.dataState}</Badge>
          {run.qualityDecision ? <Badge tone={run.qualityDecision === "blocked" ? "danger" : "neutral"}>{run.qualityDecision}</Badge> : null}
        </div>
      </div>
      <div className="mt-4 grid gap-2 text-xs sm:grid-cols-4">
        <CountPill label="Accepted" value={run.counts.accepted} />
        <CountPill label="Rejected" value={run.counts.rejected} />
        <CountPill label="Uncertain" value={run.counts.uncertain} />
        <CountPill label="Unsupported" value={run.counts.unsupported} />
      </div>
    </Link>
  )
}

function CountPill({ label, value }: { label: string; value: number }) {
  return (
    <span className="rounded-md border border-border bg-secondary/30 px-2 py-1 text-muted-foreground">
      {label}: <span className="font-semibold text-foreground">{value}</span>
    </span>
  )
}

export function NoticeList({ notices, tone = "warning" }: { notices: string[]; tone?: "success" | "warning" | "info" }) {
  if (!notices.length) return null
  return (
    <StudioNotice tone={tone} title="Evidence data notice">
      <div className="flex flex-wrap gap-2">
        {notices.map((notice) => (
          <Badge key={notice} tone={tone}>{notice}</Badge>
        ))}
      </div>
    </StudioNotice>
  )
}
