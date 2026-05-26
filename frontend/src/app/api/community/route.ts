import { NextRequest, NextResponse } from "next/server"
import { getCommunityList } from "@/lib/community/server-data"
import { communityFiltersFromSearchParams } from "@/lib/community/community-filters"

export const dynamic = "force-dynamic"

export async function GET(request: NextRequest) {
  try {
    const params = communityFiltersFromSearchParams(request.nextUrl.searchParams)
    const result = await getCommunityList(params)
    return NextResponse.json({ success: true, data: result })
  } catch (error) {
    return NextResponse.json(
      {
        success: false,
        error: {
          code: "community_request_failed",
          message: error instanceof Error ? error.message : "Community Pulse request failed"
        }
      },
      { status: 500 }
    )
  }
}
