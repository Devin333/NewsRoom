import { NextRequest, NextResponse } from "next/server"
import { getPaperById } from "@/lib/papers/real-data"
import { paperNotFoundResponse } from "@/lib/papers/public-route-guard"

export const dynamic = "force-dynamic"

export async function GET(_request: NextRequest, { params }: { params: { paperId: string } }) {
  const paper = await getPaperById(params.paperId)
  if (paper) {
    return NextResponse.json({ success: true, data: { paper } })
  }
  return paperNotFoundResponse()
}
