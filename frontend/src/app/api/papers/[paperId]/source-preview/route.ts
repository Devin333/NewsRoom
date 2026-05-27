import { NextRequest } from "next/server"
import { proxyBackendBinary } from "@/lib/paper-reader/server-proxy"

export const dynamic = "force-dynamic"

export async function GET(request: NextRequest, { params }: { params: { paperId: string } }) {
  const page = request.nextUrl.searchParams.get("page")
  const bbox = request.nextUrl.searchParams.get("bbox")
  const query = new URLSearchParams()
  if (page) query.set("page", page)
  if (bbox) query.set("bbox", bbox)
  return proxyBackendBinary(`/api/v1/papers/${encodeURIComponent(params.paperId)}/source-preview?${query.toString()}`)
}
