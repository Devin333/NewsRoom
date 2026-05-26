import { NextRequest, NextResponse } from "next/server"
import { communitySignalFiltersFromSearchParams } from "@/lib/community/community-signals"
import { getCommunitySignals } from "@/lib/community/server-data"

export const dynamic = "force-dynamic"

export async function GET(request: NextRequest) {
  try {
    const params = communitySignalFiltersFromSearchParams(request.nextUrl.searchParams)
    const result = await getCommunitySignals(params)
    return NextResponse.json({ success: true, data: result })
  } catch (error) {
    return NextResponse.json(
      {
        success: false,
        error: {
          code: "community_signals_request_failed",
          message: error instanceof Error ? error.message : "Community Pulse signals request failed"
        }
      },
      { status: 500 }
    )
  }
}
