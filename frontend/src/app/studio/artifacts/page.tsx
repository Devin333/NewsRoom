import { getArtifactRunSummaries } from "@/features/studio/artifacts/api/artifact-replay-api"
import { ArtifactReplayHomePage } from "@/features/studio/artifacts/components/artifact-replay-page"

export default async function StudioArtifactsPage() {
  const { runs, notices } = await getArtifactRunSummaries()
  return <ArtifactReplayHomePage runs={runs} notices={notices} />
}
