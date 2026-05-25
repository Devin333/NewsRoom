import { getReplayBundle } from "@/features/studio/artifacts/api/artifact-replay-api"
import { ArtifactRunReplayPage } from "@/features/studio/artifacts/components/artifact-replay-page"

export default async function StudioArtifactReplayPage({ params }: { params: { runId: string } }) {
  const { replay, lineage } = await getReplayBundle(params.runId)
  return <ArtifactRunReplayPage replay={replay} lineage={lineage} />
}
