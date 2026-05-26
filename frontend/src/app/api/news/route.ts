import { NextRequest, NextResponse } from "next/server"
import { filtersFromSearchParams } from "@/lib/news/filters"
import { getNewsListResult } from "@/lib/news/server-data"

export const dynamic = "force-dynamic"

export async function GET(request: NextRequest) {
  try {
    const filters = filtersFromSearchParams(request.nextUrl.searchParams)
    const result = await getNewsListResult(filters)
    return NextResponse.json({ success: true, data: result })
  } catch (error) {
    return NextResponse.json(
      {
        success: false,
        error: {
          code: "news_api_error",
          message: error instanceof Error ? error.message : "News API request failed",
        },
      },
      { status: 500 }
    )
  }
}
