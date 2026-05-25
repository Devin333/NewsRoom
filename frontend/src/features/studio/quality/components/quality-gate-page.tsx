import Link from "next/link"
import { Archive, FileText, GitBranch, ShieldCheck } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { BlockedRunPanel, FailureReasonPanel, RecentFailedReports } from "@/features/studio/quality/components/quality-failure-panel"
import { QualityCheckTable, QualityStatusBadge } from "@/features/studio/quality/components/quality-check-table"
import { QualityMetricBoard, QualityStatusBoard } from "@/features/studio/quality/components/quality-status-board"
import { RequestReviewButton } from "@/features/studio/quality/components/request-review-button"
import {
  StudioField,
  StudioFieldGrid,
  StudioMetricCard,
  StudioMetricGrid,
  StudioNotice,
  StudioPageHeader,
  StudioPanel,
  StudioTableFrame
} from "@/features/studio/shared/components/studio-dashboard"
import type {
  StudioQualityDashboard,
  StudioQualityDetail,
  StudioRequestReviewAction
} from "@/types/quality"

export function QualityGatePage({ dashboard }: { dashboard: StudioQualityDashboard }) {
  return (
    <main className="space-y-6">
      <StudioPageHeader
        eyebrow="Governance"
        title="Quality Gate"
        description="Govern report quality, run health, diagnostics, and human review routing before publish."
        meta={<Badge variant={dashboard.dataState === "ready" ? "success" : dashboard.dataState === "partial" ? "warning" : "muted"}>{dashboard.dataState}</Badge>}
      />

      <NoticeList notices={dashboard.notices} dataState={dashboard.dataState} />
      <QualityStatusBoard dashboard={dashboard} />
      <QualityMetricBoard dashboard={dashboard} />

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <RecentFailedReports reports={dashboard.recentFailedReports} />
        <BlockedRunPanel runs={dashboard.recentBlockedRuns} />
      </section>

      <StudioPanel title="Report gate catalog" description="Reports returned by the quality catalog and their current gate state." contentClassName="p-0">
        <StudioTableFrame className="border-0 shadow-none">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] border-collapse text-left text-sm">
              <thead className="border-b border-border bg-secondary/80 text-xs uppercase text-muted-foreground">
                <tr>
                  <th className="px-4 py-3 font-medium">Report</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Quality</th>
                </tr>
              </thead>
              <tbody>
                {dashboard.reports.map((report) => (
                  <tr key={report.reportId} className="border-b border-border/70 last:border-b-0 hover:bg-secondary/40">
                    <td className="px-4 py-3">
                      <Link href={`/studio/quality/reports/${encodeURIComponent(report.reportId)}`} className="block min-w-0">
                        <p className="truncate text-sm font-medium text-foreground">{report.title}</p>
                        <p className="mt-1 truncate font-mono text-xs text-muted-foreground">{report.reportId}</p>
                      </Link>
                    </td>
                    <td className="px-4 py-3"><QualityStatusBadge status={report.status} /></td>
                    <td className="px-4 py-3 text-sm text-muted-foreground">{report.qualityScore === undefined ? "n/a" : `${report.qualityScore}%`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </StudioTableFrame>
      </StudioPanel>
    </main>
  )
}

export function QualityReportDetailPage({
  detail,
  requestReviewAction
}: {
  detail: StudioQualityDetail
  requestReviewAction: StudioRequestReviewAction
}) {
  return (
    <main className="space-y-6">
      <StudioPageHeader
        eyebrow="Report Quality"
        title={detail.report.title}
        description="Inspect gate checks, failed conditions, run health, diagnostics, artifacts, and review routing."
        actions={
          <RequestReviewButton
            reportId={detail.report.reportId}
            dataState={detail.dataState}
            requestReviewAction={requestReviewAction}
          />
        }
        meta={<Badge variant={detail.dataState === "ready" ? "success" : detail.dataState === "partial" ? "warning" : "muted"}>{detail.dataState}</Badge>}
      />

      <NoticeList notices={detail.notices} dataState={detail.dataState} />

      <StudioMetricGrid className="xl:grid-cols-4 2xl:grid-cols-4">
        <StudioMetricCard label="Gate status" value={<QualityStatusBadge status={detail.report.status} />} detail={detail.report.reportId} icon={ShieldCheck} />
        <StudioMetricCard label="Quality score" value={detail.report.qualityScore === undefined ? "n/a" : `${detail.report.qualityScore}%`} detail="Report score" icon={FileText} tone={detail.report.status === "failed" ? "danger" : "accent"} />
        <StudioMetricCard label="Linked run" value={<span className="text-sm">{detail.report.runId ?? "n/a"}</span>} detail="Runtime lineage" icon={GitBranch} />
        <StudioMetricCard label="Artifacts" value={detail.artifactRefs.length} detail={detail.report.artifactPath ?? detail.artifactRefs[0]?.value ?? "n/a"} icon={Archive} />
      </StudioMetricGrid>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <QualityCheckTable checks={detail.checks} />
        <div className="space-y-4">
          <FailureReasonPanel reasons={detail.failureReasons} />
          <StudioPanel title="Gate metrics">
            <StudioFieldGrid className="xl:grid-cols-1">
              <StudioField label="Citation coverage" value={formatMetric(detail.metrics.citationCoverage)} />
              <StudioField label="Source freshness" value={formatMetric(detail.metrics.sourceFreshness)} />
              <StudioField label="Duplicate rate" value={formatMetric(detail.metrics.duplicateRate)} />
              <StudioField label="Unsupported claims" value={String(detail.metrics.unsupportedClaims)} />
            </StudioFieldGrid>
          </StudioPanel>
          <StudioPanel title="Artifacts" contentClassName="space-y-2">
            {detail.artifactRefs.length ? (
              detail.artifactRefs.map((artifact) => (
                <div key={`${artifact.label}-${artifact.value}`} className="rounded-md border border-border bg-background p-2">
                  <p className="text-xs text-muted-foreground">{artifact.label}</p>
                  <p className="mt-1 truncate font-mono text-sm text-foreground">{artifact.value}</p>
                </div>
              ))
            ) : (
              <p className="text-sm text-muted-foreground">No artifact refs were returned in the quality payload.</p>
            )}
          </StudioPanel>
        </div>
      </section>
    </main>
  )
}

function NoticeList({ notices, dataState }: { notices: string[]; dataState: string }) {
  if (!notices.length) return null
  return (
    <StudioNotice tone={dataState === "ready" ? "success" : "warning"} title="Quality data notice">
      <div className="mb-2">
        <Badge variant={dataState === "ready" ? "success" : dataState === "partial" ? "warning" : "muted"}>
          {dataState}
        </Badge>
      </div>
      <div className="space-y-1">
        {notices.map((notice) => (
          <p key={notice}>{notice}</p>
        ))}
      </div>
    </StudioNotice>
  )
}

function formatMetric(value?: number): string {
  return value === undefined ? "n/a" : `${value}%`
}
