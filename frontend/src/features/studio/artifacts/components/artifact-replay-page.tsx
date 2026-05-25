"use client"

import Link from "next/link"
import { Archive, Eye, RotateCcw } from "lucide-react"
import { EmptyState } from "@/components/common/empty-state"
import { Button } from "@/components/ui/button"
import { ArtifactNotice } from "@/features/studio/artifacts/components/artifact-notice"
import { ArtifactPreview } from "@/features/studio/artifacts/components/artifact-preview"
import { ArtifactRunSummaryGrid } from "@/features/studio/artifacts/components/artifact-run-summary-grid"
import { ArtifactListPanel } from "@/features/studio/artifacts/components/artifact-list-panel"
import { ArtifactStatusBadge } from "@/features/studio/artifacts/components/artifact-status-badge"
import { LineageViewer } from "@/features/studio/artifacts/components/lineage-viewer"
import { ReplayBundleViewer } from "@/features/studio/artifacts/components/replay-bundle-viewer"
import {
  StudioField,
  StudioFieldGrid,
  StudioPageHeader,
  StudioPanel,
  StudioTableFrame
} from "@/features/studio/shared/components/studio-dashboard"
import { formatDateTime, formatNumber } from "@/lib/format"
import { useI18n } from "@/lib/i18n/use-i18n"
import type { StudioArtifactRunDetail, StudioArtifactRunSummary, StudioLineageRef, StudioReplayBundle } from "@/types/artifact"

export function ArtifactReplayHomePage({ runs, notices }: { runs: StudioArtifactRunSummary[]; notices: string[] }) {
  const { locale, t } = useI18n()
  return (
    <main className="space-y-6">
      <StudioPageHeader
        eyebrow={locale === "zh" ? "运行时" : "Runtime"}
        title={t("studio.module.artifactReplay.title")}
        description={t("studio.module.artifactReplay.description")}
      />
      <ArtifactNotice notices={notices} />

      <StudioPanel title={t("studio.artifacts.recentRuns")} description={t("studio.artifacts.recentRunsDescription")} contentClassName="p-0">
        {!runs.length ? (
          <div className="p-4">
            <EmptyState title={t("studio.artifacts.noRuns")} description={t("studio.artifacts.noRunsDescription")} />
          </div>
        ) : (
          <StudioTableFrame className="border-0 shadow-none">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[1080px] border-collapse text-left text-sm">
                <thead className="border-b border-border bg-secondary/80 text-xs uppercase text-muted-foreground">
                  <tr>
                    <th className="px-4 py-3 font-medium">{t("studio.runs.runId")}</th>
                    <th className="px-4 py-3 font-medium">{t("common.status")}</th>
                    <th className="px-4 py-3 font-medium">{t("studio.quality.artifacts")}</th>
                    <th className="px-4 py-3 font-medium">{t("studio.artifacts.events")}</th>
                    <th className="px-4 py-3 font-medium">{t("studio.artifacts.stepResults")}</th>
                    <th className="px-4 py-3 font-medium">{t("studio.artifacts.manifest")}</th>
                    <th className="px-4 py-3 font-medium">{t("studio.runs.started")}</th>
                    <th className="px-4 py-3 font-medium">{t("common.actions")}</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((run) => (
                    <tr key={run.runId} className="border-b border-border/70 last:border-b-0 hover:bg-secondary/40">
                      <td className="max-w-[16rem] px-4 py-3">
                        <p className="truncate font-medium">{run.runId}</p>
                        <p className="truncate text-xs text-muted-foreground">{run.workflowId ?? t("studio.artifacts.unknownWorkflow")}</p>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-2">
                          <ArtifactStatusBadge status={run.artifactStatus} />
                          <span className="text-xs text-muted-foreground">{run.status}</span>
                        </div>
                      </td>
                      <td className="px-4 py-3">{formatNumber(run.artifactCount)}</td>
                      <td className="px-4 py-3">{formatNumber(run.eventCount)}</td>
                      <td className="px-4 py-3">{formatNumber(run.stepResultCount)}</td>
                      <td className="max-w-[18rem] truncate px-4 py-3">{run.manifestPath ?? t("studio.artifacts.noManifestPath")}</td>
                      <td className="px-4 py-3">{formatDateTime(run.startedAt)}</td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-2">
                          <Button asChild variant="outline" size="sm">
                            <Link href={`/studio/artifacts/runs/${encodeURIComponent(run.runId)}`}>
                              <Eye className="size-4" />
                              {t("studio.artifacts.view")}
                            </Link>
                          </Button>
                          <Button asChild variant="ghost" size="sm">
                            <Link href={`/studio/artifacts/runs/${encodeURIComponent(run.runId)}/replay`}>
                              <RotateCcw className="size-4" />
                              {t("studio.artifacts.replay")}
                            </Link>
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </StudioTableFrame>
        )}
      </StudioPanel>
    </main>
  )
}

export function ArtifactRunDetailPage({
  detail,
  selectedArtifactKey
}: {
  detail: StudioArtifactRunDetail
  selectedArtifactKey?: string
}) {
  const { t } = useI18n()
  const selectedArtifact =
    detail.artifacts.find((artifact) => artifact.artifactKey === selectedArtifactKey) ?? detail.selectedArtifact

  return (
    <main className="space-y-6">
      <StudioPageHeader
        eyebrow={t("studio.module.artifactReplay.title")}
        title={t("studio.artifacts.runArtifacts")}
        description={t("studio.artifacts.runArtifactsDescription")}
        actions={
          <Button asChild variant="outline">
            <Link href={`/studio/artifacts/runs/${encodeURIComponent(detail.run.runId)}/replay`}>
              <RotateCcw className="size-4" />
              {t("studio.artifacts.replayBundle")}
            </Link>
          </Button>
        }
        meta={<ArtifactStatusBadge status={detail.run.artifactStatus} />}
      />
      <ArtifactNotice notices={[...detail.run.notices, ...detail.notices]} />
      <ArtifactRunSummaryGrid run={detail.run} />

      <StudioPanel title={t("studio.artifacts.runMetadata")} description={detail.run.runId} actions={<ArtifactStatusBadge status={detail.run.artifactStatus} />}>
        <StudioFieldGrid>
          <StudioField label={t("studio.artifacts.workflow")} value={detail.run.workflowId ?? t("common.unknown")} />
          <StudioField label={t("studio.artifacts.profile")} value={detail.run.profile ?? t("common.unknown")} />
          <StudioField label={t("studio.artifacts.manifest")} value={detail.run.manifestPath ?? t("studio.artifacts.noManifestPath")} />
          <StudioField label={t("studio.artifacts.finished")} value={formatDateTime(detail.run.finishedAt)} />
        </StudioFieldGrid>
      </StudioPanel>

      <section className="grid gap-4 xl:grid-cols-[minmax(18rem,0.9fr)_minmax(0,1.4fr)]">
        <ArtifactListPanel runId={detail.run.runId} artifacts={detail.artifacts} selectedArtifactKey={selectedArtifact?.artifactKey} />
        <ArtifactPreview artifact={selectedArtifact} />
      </section>

      {detail.replay ? (
        <ReplayDigest replay={detail.replay} />
      ) : (
        <EmptyState title={t("studio.artifacts.noReplayDigest")} description={t("studio.artifacts.noReplayDigestDescription")} />
      )}
      <LineageViewer lineage={detail.lineage} />
    </main>
  )
}

export function ArtifactRunReplayPage({
  replay,
  lineage
}: {
  replay: StudioReplayBundle
  lineage: StudioLineageRef[]
}) {
  const { t } = useI18n()
  return (
    <main className="space-y-6">
      <StudioPageHeader
        eyebrow={t("studio.module.artifactReplay.title")}
        title={t("studio.artifacts.replayBundle")}
        description={t("studio.artifacts.replayBundleDescription")}
        actions={
          <Button asChild variant="outline">
            <Link href={`/studio/artifacts/runs/${encodeURIComponent(replay.runId)}`}>
              <Archive className="size-4" />
              {t("studio.artifacts.backToArtifacts")}
            </Link>
          </Button>
        }
      />
      <ArtifactNotice notices={replay.notices} />
      <ReplayBundleViewer replay={replay} />
      <LineageViewer lineage={lineage} />
    </main>
  )
}

function ReplayDigest({ replay }: { replay: StudioReplayBundle }) {
  const { t } = useI18n()
  return (
    <StudioPanel
      title={t("studio.artifacts.replayDigest")}
      description={replay.manifestPath ?? t("studio.artifacts.noManifestPath")}
      actions={
        <Button asChild variant="ghost" size="sm">
          <Link href={`/studio/artifacts/runs/${encodeURIComponent(replay.runId)}/replay`}>
            <RotateCcw className="size-4" />
            {t("studio.artifacts.openReplay")}
          </Link>
        </Button>
      }
    >
      <StudioFieldGrid>
        <StudioField label={t("studio.artifacts.events")} value={formatNumber(replay.eventCount)} />
        <StudioField label={t("studio.quality.artifacts")} value={formatNumber(replay.artifactCount)} />
        <StudioField label={t("studio.artifacts.stepResults")} value={formatNumber(replay.stepResultCount)} />
        <StudioField label={t("studio.artifacts.readiness")} value={replay.readinessLabel} />
      </StudioFieldGrid>
    </StudioPanel>
  )
}
