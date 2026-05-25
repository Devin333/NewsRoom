"use client"

import { ArtifactReplayHomePage } from "@/features/studio/artifacts/components/artifact-replay-page"
import type { StudioArtifactRunSummary } from "@/types/artifact"

export function ArtifactsPageClient({
  runs,
  notices = []
}: {
  runs: StudioArtifactRunSummary[]
  notices?: string[]
}) {
  return <ArtifactReplayHomePage runs={runs} notices={notices} />
}
