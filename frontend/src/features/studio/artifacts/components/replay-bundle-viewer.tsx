import { AlertTriangle, Archive, CheckCircle2, FileJson2, ListTree, ShieldCheck, Workflow } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { ArtifactPreview } from "@/features/studio/artifacts/components/artifact-preview"
import { ReplayReadinessBadge } from "@/features/studio/artifacts/components/artifact-status-badge"
import { StudioMetricCard, StudioMetricGrid, StudioNotice, StudioPanel } from "@/features/studio/shared/components/studio-dashboard"
import type { StudioReplayBundle } from "@/types/artifact"

export function ReplayBundleViewer({ replay }: { replay: StudioReplayBundle }) {
  const integrityValid = replay.integrity.valid === true

  return (
    <div className="space-y-4">
      <StudioMetricGrid className="xl:grid-cols-5 2xl:grid-cols-5">
        <StudioMetricCard label="Readiness" value={<ReplayReadinessBadge replay={replay} />} detail={replay.ready ? "Replay ready" : "Review required"} icon={ShieldCheck} tone={replay.ready ? "success" : "warning"} />
        <StudioMetricCard label="Events" value={String(replay.eventCount)} detail="Replay event records" icon={Workflow} />
        <StudioMetricCard label="Artifacts" value={String(replay.artifactCount)} detail="Replay artifacts" icon={Archive} />
        <StudioMetricCard label="Step results" value={String(replay.stepResultCount)} detail="Step result payloads" icon={ListTree} />
        <StudioMetricCard label="Integrity" value={<Badge variant={integrityValid ? "success" : "warning"}>{integrityValid ? "valid" : "check"}</Badge>} detail="Bundle validation" icon={integrityValid ? CheckCircle2 : AlertTriangle} tone={integrityValid ? "success" : "warning"} />
      </StudioMetricGrid>

      {replay.eventsError ? (
        <StudioNotice tone="danger" title="Replay events error">
          {replay.eventsError}
        </StudioNotice>
      ) : null}

      <Tabs defaultValue="manifest">
        <TabsList className="flex h-auto flex-wrap justify-start">
          <TabsTrigger value="manifest">Manifest</TabsTrigger>
          <TabsTrigger value="events">Events</TabsTrigger>
          <TabsTrigger value="artifacts">Artifacts</TabsTrigger>
          <TabsTrigger value="steps">Step results</TabsTrigger>
          <TabsTrigger value="integrity">Integrity</TabsTrigger>
        </TabsList>
        <TabsContent value="manifest">
          <JsonPanel title="manifest.json" value={replay.manifest} />
        </TabsContent>
        <TabsContent value="events">
          <JsonPanel title="events" value={replay.events} />
        </TabsContent>
        <TabsContent value="artifacts">
          <div className="space-y-4">
            {replay.artifacts.map((artifact) => (
              <ArtifactPreview key={artifact.artifactKey} artifact={artifact} />
            ))}
          </div>
        </TabsContent>
        <TabsContent value="steps">
          <JsonPanel title="step_results" value={replay.stepResults} />
        </TabsContent>
        <TabsContent value="integrity">
          <JsonPanel title="integrity" value={replay.integrity} />
        </TabsContent>
      </Tabs>
    </div>
  )
}

function JsonPanel({ title, value }: { title: string; value: unknown }) {
  const isIntegrity = title === "integrity" && typeof value === "object" && value && "valid" in value
  const valid = isIntegrity && (value as { valid?: unknown }).valid === true
  return (
    <StudioPanel
      title={title}
      actions={isIntegrity ? (valid ? <CheckCircle2 className="size-4 text-success" /> : <AlertTriangle className="size-4 text-warning" />) : <FileJson2 className="size-4 text-muted-foreground" />}
    >
      <pre className="max-h-[36rem] overflow-auto whitespace-pre-wrap break-words rounded-md border border-border bg-background p-4 text-xs leading-6">
        {JSON.stringify(value, null, 2)}
      </pre>
    </StudioPanel>
  )
}
