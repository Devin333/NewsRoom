"use client"

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
import { useI18n } from "@/lib/i18n/use-i18n"
import type { StudioEvidenceOverview, StudioEvidenceRunSummary } from "@/types/evidence"

export function EvidenceCenterPage({ overview }: { overview: StudioEvidenceOverview }) {
  const { t } = useI18n()
  return (
    <main className="space-y-6">
      <StudioPageHeader
        eyebrow={t("studio.nav.business")}
        title={t("studio.module.evidenceCenter.title")}
        description={t("studio.module.evidenceCenter.description")}
      />
      <NoticeList notices={overview.notices} tone={overview.dataState === "ready" ? "success" : "warning"} />
      <StudioMetricGrid className="xl:grid-cols-5 2xl:grid-cols-5">
        <StudioMetricCard label={t("studio.evidence.claims")} value={overview.totals.total} detail={t("studio.evidence.totalClaims")} icon={Network} tone="accent" />
        <StudioMetricCard label={t("studio.evidence.accepted")} value={overview.totals.accepted} detail={t("studio.evidence.supportedClaims")} icon={CheckCircle2} tone="success" />
        <StudioMetricCard label={t("studio.evidence.rejected")} value={overview.totals.rejected} detail={t("studio.evidence.rejectedClaims")} icon={XCircle} tone="danger" />
        <StudioMetricCard label={t("studio.evidence.uncertain")} value={overview.totals.uncertain} detail={t("studio.evidence.needsReview")} icon={CircleHelp} tone="warning" />
        <StudioMetricCard label={t("studio.evidence.unsupported")} value={overview.totals.unsupported} detail={t("studio.evidence.supportMissing")} icon={FileWarning} tone="info" />
      </StudioMetricGrid>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <StudioPanel title={t("studio.evidence.recentHealth")} description={t("studio.evidence.recentHealthDescription")} contentClassName="space-y-3">
          {overview.runs.length ? overview.runs.map((run) => <RunSummaryRow key={run.runId} run={run} />) : <p className="text-sm text-muted-foreground">{t("studio.evidence.noRecentRuns")}</p>}
        </StudioPanel>
        <StudioPanel title={t("studio.evidence.citationFailures")} description={t("studio.evidence.citationFailuresDescription")} contentClassName="space-y-3">
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
            <p className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">{t("studio.evidence.noCitationFailures")}</p>
          )}
        </StudioPanel>
      </section>
    </main>
  )
}

function RunSummaryRow({ run }: { run: StudioEvidenceRunSummary }) {
  const { t, dataState, status } = useI18n()
  const href = `/studio/evidence/runs/${encodeURIComponent(run.runId)}${run.reportId ? `?reportId=${encodeURIComponent(run.reportId)}` : ""}`
  return (
    <Link href={href} className="block rounded-md border border-border bg-background p-4 transition-colors hover:bg-secondary/40">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="break-words font-medium text-foreground">{run.workflowName ?? run.runId}</p>
          <p className="mt-1 break-words font-mono text-xs text-muted-foreground">{run.runId}</p>
          {run.reportId ? <p className="mt-1 break-words text-xs text-muted-foreground">{t("studio.evidence.report")} {run.reportId}</p> : null}
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge tone={run.dataState === "ready" ? "success" : run.dataState === "fallback" ? "info" : "warning"}>{dataState(run.dataState)}</Badge>
          {run.qualityDecision ? <Badge tone={run.qualityDecision === "blocked" ? "danger" : "neutral"}>{status(run.qualityDecision)}</Badge> : null}
        </div>
      </div>
      <div className="mt-4 grid gap-2 text-xs sm:grid-cols-4">
        <CountPill label={t("studio.evidence.accepted")} value={run.counts.accepted} />
        <CountPill label={t("studio.evidence.rejected")} value={run.counts.rejected} />
        <CountPill label={t("studio.evidence.uncertain")} value={run.counts.uncertain} />
        <CountPill label={t("studio.evidence.unsupported")} value={run.counts.unsupported} />
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
  const { t } = useI18n()
  if (!notices.length) return null
  return (
    <StudioNotice tone={tone} title={t("studio.evidence.dataNotice")}>
      <div className="flex flex-wrap gap-2">
        {notices.map((notice) => (
          <Badge key={notice} tone={tone}>{notice}</Badge>
        ))}
      </div>
    </StudioNotice>
  )
}
