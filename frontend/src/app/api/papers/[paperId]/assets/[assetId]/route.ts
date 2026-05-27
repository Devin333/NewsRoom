import { NextRequest } from "next/server"
import { proxyBackendBinary } from "@/lib/paper-reader/server-proxy"

export const dynamic = "force-dynamic"

export async function GET(_request: NextRequest, { params }: { params: { paperId: string; assetId: string } }) {
  return proxyBackendBinary(
    `/api/v1/papers/${encodeURIComponent(params.paperId)}/assets/${encodeURIComponent(params.assetId)}`,
  )
}
