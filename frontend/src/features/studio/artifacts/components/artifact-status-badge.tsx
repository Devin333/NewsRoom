import { Badge } from "@/components/ui/badge"
import type { StudioArtifactRunSummary, StudioReplayBundle } from "@/types/artifact"

export function ArtifactStatusBadge({ status }: { status: StudioArtifactRunSummary["artifactStatus"] }) {
  const config: Record<StudioArtifactRunSummary["artifactStatus"], { label: string; variant: "success" | "warning" | "muted" | "danger" }> = {
    ready: { label: "Ready", variant: "success" },
    partial: { label: "Partial", variant: "warning" },
    missing: { label: "Missing", variant: "muted" },
    error: { label: "Error", variant: "danger" }
  }
  const item = config[status]
  return <Badge variant={item.variant}>{item.label}</Badge>
}

export function ReplayReadinessBadge({ replay }: { replay: StudioReplayBundle }) {
  return <Badge variant={replay.ready ? "success" : "warning"}>{replay.readinessLabel}</Badge>
}
