import { NextRequest } from "next/server"
import { proxyBackendBinary } from "@/lib/paper-reader/server-proxy"
import { requirePublicPaper } from "@/lib/papers/public-route-guard"

export const dynamic = "force-dynamic"

export async function GET(_request: NextRequest, { params }: { params: { paperId: string; assetId: string } }) {
  const guard = await requirePublicPaper(params.paperId)
  if (!guard.ok) {
    return guard.response
  }

  return proxyBackendBinary(
    `/api/v1/papers/${encodeURIComponent(guard.paper.id)}/assets/${encodeURIComponent(params.assetId)}`,
  )
}
