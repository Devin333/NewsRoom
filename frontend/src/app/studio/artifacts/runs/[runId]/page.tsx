import { getArtifactRunDetail, getArtifactRunDetailWithArtifact } from "@/features/studio/artifacts/api/artifact-replay-api"
import { ArtifactRunDetailPage } from "@/features/studio/artifacts/components/artifact-replay-page"

export default async function StudioArtifactRunPage({
  params,
  searchParams
}: {
  params: { runId: string }
  searchParams?: { artifact?: string }
}) {
  const detail = searchParams?.artifact
    ? await getArtifactRunDetailWithArtifact(params.runId, searchParams.artifact)
    : await getArtifactRunDetail(params.runId)
  return <ArtifactRunDetailPage detail={detail} selectedArtifactKey={searchParams?.artifact} />
}
