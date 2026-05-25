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
import type { StudioArtifactRunDetail, StudioArtifactRunSummary, StudioLineageRef, StudioReplayBundle } from "@/types/artifact"

export function ArtifactReplayHomePage({ runs, notices }: { runs: StudioArtifactRunSummary[]; notices: string[] }) {
  return (
    <main className="space-y-6">
      <StudioPageHeader
        eyebrow="Runtime"
        title="Artifact / Replay"
        description="Inspect run manifests, events, step results, artifacts, replay bundles, and lineage."
      />
      <ArtifactNotice notices={notices} />

      <StudioPanel title="Recent runs" description="Runs with artifact or replay material." contentClassName="p-0">
        {!runs.length ? (
          <div className="p-4">
            <EmptyState title="No runs" description="The backend did not return inspectable runs." />
          </div>
        ) : (
          <StudioTableFrame className="border-0 shadow-none">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[1080px] border-collapse text-left text-sm">
                <thead className="border-b border-border bg-secondary/80 text-xs uppercase text-muted-foreground">
                  <tr>
                    <th className="px-4 py-3 font-medium">Run</th>
                    <th className="px-4 py-3 font-medium">Status</th>
                    <th className="px-4 py-3 font-medium">Artifacts</th>
                    <th className="px-4 py-3 font-medium">Events</th>
                    <th className="px-4 py-3 font-medium">Step results</th>
                    <th className="px-4 py-3 font-medium">Manifest</th>
                    <th className="px-4 py-3 font-medium">Started</th>
                    <th className="px-4 py-3 font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((run) => (
                    <tr key={run.runId} className="border-b border-border/70 last:border-b-0 hover:bg-secondary/40">
                      <td className="max-w-[16rem] px-4 py-3">
                        <p className="truncate font-medium">{run.runId}</p>
                        <p className="truncate text-xs text-muted-foreground">{run.workflowId ?? "unknown workflow"}</p>
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
                      <td className="max-w-[18rem] truncate px-4 py-3">{run.manifestPath ?? "No manifest path"}</td>
                      <td className="px-4 py-3">{formatDateTime(run.startedAt)}</td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-2">
                          <Button asChild variant="outline" size="sm">
                            <Link href={`/studio/artifacts/runs/${encodeURIComponent(run.runId)}`}>
                              <Eye className="size-4" />
                              View
                            </Link>
                          </Button>
                          <Button asChild variant="ghost" size="sm">
                            <Link href={`/studio/artifacts/runs/${encodeURIComponent(run.runId)}/replay`}>
                              <RotateCcw className="size-4" />
                              Replay
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
  const selectedArtifact =
    detail.artifacts.find((artifact) => artifact.artifactKey === selectedArtifactKey) ?? detail.selectedArtifact

  return (
    <main className="space-y-6">
      <StudioPageHeader
        eyebrow="Artifact Replay"
        title="Run artifacts"
        description="Inspect artifacts, manifest, events, step results, previews, and lineage for this run."
        actions={
          <Button asChild variant="outline">
            <Link href={`/studio/artifacts/runs/${encodeURIComponent(detail.run.runId)}/replay`}>
              <RotateCcw className="size-4" />
              Replay bundle
            </Link>
          </Button>
        }
        meta={<ArtifactStatusBadge status={detail.run.artifactStatus} />}
      />
      <ArtifactNotice notices={[...detail.run.notices, ...detail.notices]} />
      <ArtifactRunSummaryGrid run={detail.run} />

      <StudioPanel title="Run metadata" description={detail.run.runId} actions={<ArtifactStatusBadge status={detail.run.artifactStatus} />}>
        <StudioFieldGrid>
          <StudioField label="Workflow" value={detail.run.workflowId ?? "unknown"} />
          <StudioField label="Profile" value={detail.run.profile ?? "unknown"} />
          <StudioField label="Manifest path" value={detail.run.manifestPath ?? "No manifest path"} />
          <StudioField label="Finished" value={formatDateTime(detail.run.finishedAt)} />
        </StudioFieldGrid>
      </StudioPanel>

      <section className="grid gap-4 xl:grid-cols-[minmax(18rem,0.9fr)_minmax(0,1.4fr)]">
        <ArtifactListPanel runId={detail.run.runId} artifacts={detail.artifacts} selectedArtifactKey={selectedArtifact?.artifactKey} />
        <ArtifactPreview artifact={selectedArtifact} />
      </section>

      {detail.replay ? (
        <ReplayDigest replay={detail.replay} />
      ) : (
        <EmptyState title="No replay digest" description="This run did not return a replay bundle." />
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
  return (
    <main className="space-y-6">
      <StudioPageHeader
        eyebrow="Artifact Replay"
        title="Replay bundle"
        description="Review the manifest, events, artifacts, step results, integrity payload, and events errors for replay."
        actions={
          <Button asChild variant="outline">
            <Link href={`/studio/artifacts/runs/${encodeURIComponent(replay.runId)}`}>
              <Archive className="size-4" />
              Back to artifacts
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
  return (
    <StudioPanel
      title="Replay digest"
      description={replay.manifestPath ?? "No manifest path"}
      actions={
        <Button asChild variant="ghost" size="sm">
          <Link href={`/studio/artifacts/runs/${encodeURIComponent(replay.runId)}/replay`}>
            <RotateCcw className="size-4" />
            Open Replay
          </Link>
        </Button>
      }
    >
      <StudioFieldGrid>
        <StudioField label="Events" value={formatNumber(replay.eventCount)} />
        <StudioField label="Artifacts" value={formatNumber(replay.artifactCount)} />
        <StudioField label="Step results" value={formatNumber(replay.stepResultCount)} />
        <StudioField label="Readiness" value={replay.readinessLabel} />
      </StudioFieldGrid>
    </StudioPanel>
  )
}
