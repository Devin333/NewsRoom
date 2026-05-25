"use client"

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
import { useI18n } from "@/lib/i18n/use-i18n"
import type {
  StudioQualityDashboard,
  StudioQualityDetail,
  StudioRequestReviewAction
} from "@/types/quality"

export function QualityGatePage({ dashboard }: { dashboard: StudioQualityDashboard }) {
  const { t, dataState } = useI18n()
  return (
    <main className="space-y-6">
      <StudioPageHeader
        eyebrow={t("studio.nav.governance")}
        title={t("studio.module.qualityGate.title")}
        description={t("studio.module.qualityGate.description")}
        meta={<Badge variant={dashboard.dataState === "ready" ? "success" : dashboard.dataState === "partial" ? "warning" : "muted"}>{dataState(dashboard.dataState)}</Badge>}
      />

      <NoticeList notices={dashboard.notices} dataState={dashboard.dataState} />
      <QualityStatusBoard dashboard={dashboard} />
      <QualityMetricBoard dashboard={dashboard} />

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <RecentFailedReports reports={dashboard.recentFailedReports} />
        <BlockedRunPanel runs={dashboard.recentBlockedRuns} />
      </section>

      <StudioPanel title={t("studio.quality.reportGateCatalog")} description={t("studio.quality.reportGateCatalogDescription")} contentClassName="p-0">
        <StudioTableFrame className="border-0 shadow-none">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] border-collapse text-left text-sm">
              <thead className="border-b border-border bg-secondary/80 text-xs uppercase text-muted-foreground">
                <tr>
                  <th className="px-4 py-3 font-medium">{t("studio.quality.report")}</th>
                  <th className="px-4 py-3 font-medium">{t("common.status")}</th>
                  <th className="px-4 py-3 font-medium">{t("studio.quality.qualityScore")}</th>
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
  const { t, dataState } = useI18n()
  return (
    <main className="space-y-6">
      <StudioPageHeader
        eyebrow={t("studio.quality.reportQuality")}
        title={detail.report.title}
        description={t("studio.quality.detailDescription")}
        actions={
          <RequestReviewButton
            reportId={detail.report.reportId}
            dataState={detail.dataState}
            requestReviewAction={requestReviewAction}
          />
        }
        meta={<Badge variant={detail.dataState === "ready" ? "success" : detail.dataState === "partial" ? "warning" : "muted"}>{dataState(detail.dataState)}</Badge>}
      />

      <NoticeList notices={detail.notices} dataState={detail.dataState} />

      <StudioMetricGrid className="xl:grid-cols-4 2xl:grid-cols-4">
        <StudioMetricCard label={t("studio.quality.gateStatus")} value={<QualityStatusBadge status={detail.report.status} />} detail={detail.report.reportId} icon={ShieldCheck} />
        <StudioMetricCard label={t("studio.quality.qualityScore")} value={detail.report.qualityScore === undefined ? "n/a" : `${detail.report.qualityScore}%`} detail={t("studio.quality.reportScore")} icon={FileText} tone={detail.report.status === "failed" ? "danger" : "accent"} />
        <StudioMetricCard label={t("studio.quality.linkedRun")} value={<span className="text-sm">{detail.report.runId ?? "n/a"}</span>} detail={t("studio.quality.runtimeLineage")} icon={GitBranch} />
        <StudioMetricCard label={t("studio.quality.artifacts")} value={detail.artifactRefs.length} detail={detail.report.artifactPath ?? detail.artifactRefs[0]?.value ?? "n/a"} icon={Archive} />
      </StudioMetricGrid>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <QualityCheckTable checks={detail.checks} />
        <div className="space-y-4">
          <FailureReasonPanel reasons={detail.failureReasons} />
          <StudioPanel title={t("studio.quality.gateMetrics")}>
            <StudioFieldGrid className="xl:grid-cols-1">
              <StudioField label={t("studio.quality.citationCoverage")} value={formatMetric(detail.metrics.citationCoverage)} />
              <StudioField label={t("studio.quality.sourceFreshness")} value={formatMetric(detail.metrics.sourceFreshness)} />
              <StudioField label={t("studio.quality.duplicateRate")} value={formatMetric(detail.metrics.duplicateRate)} />
              <StudioField label={t("studio.quality.unsupportedClaims")} value={String(detail.metrics.unsupportedClaims)} />
            </StudioFieldGrid>
          </StudioPanel>
          <StudioPanel title={t("studio.quality.artifacts")} contentClassName="space-y-2">
            {detail.artifactRefs.length ? (
              detail.artifactRefs.map((artifact) => (
                <div key={`${artifact.label}-${artifact.value}`} className="rounded-md border border-border bg-background p-2">
                  <p className="text-xs text-muted-foreground">{artifact.label}</p>
                  <p className="mt-1 truncate font-mono text-sm text-foreground">{artifact.value}</p>
                </div>
              ))
            ) : (
              <p className="text-sm text-muted-foreground">{t("studio.quality.noArtifactRefs")}</p>
            )}
          </StudioPanel>
        </div>
      </section>
    </main>
  )
}

function NoticeList({ notices, dataState }: { notices: string[]; dataState: string }) {
  const { t, dataState: formatDataState } = useI18n()
  if (!notices.length) return null
  return (
    <StudioNotice tone={dataState === "ready" ? "success" : "warning"} title={t("studio.quality.dataNotice")}>
      <div className="mb-2">
        <Badge variant={dataState === "ready" ? "success" : dataState === "partial" ? "warning" : "muted"}>
          {formatDataState(dataState)}
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
