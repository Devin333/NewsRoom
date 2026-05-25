import { NextRequest, NextResponse } from "next/server"
import { getPdfProxyStats, normalizePdfProxyStatsWindow } from "@/lib/papers/pdf-proxy-metrics"

export const dynamic = "force-dynamic"
export const runtime = "nodejs"

export async function GET(request: NextRequest) {
  try {
    const stats = await getPdfProxyStats({
      windowHours: normalizePdfProxyStatsWindow(request.nextUrl.searchParams.get("windowHours"))
    })
    return NextResponse.json({
      success: true,
      data: { stats },
      request_id: null
    })
  } catch (error) {
    return NextResponse.json(
      {
        success: false,
        error: {
          code: "pdf_proxy_stats_unavailable",
          message: error instanceof Error ? error.message : "PDF proxy stats unavailable"
        },
        request_id: null
      },
      { status: 500 }
    )
  }
}
