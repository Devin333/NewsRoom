import { NextResponse } from "next/server"
import { getDashboardOverview } from "@/lib/dashboard/overview-source"

export const dynamic = "force-dynamic"

export async function GET() {
  try {
    const overview = await getDashboardOverview()
    return NextResponse.json({ success: true, data: overview, error: null })
  } catch (error) {
    return NextResponse.json(
      {
        success: false,
        data: null,
        error: {
          code: "dashboard_overview_failed",
          message: error instanceof Error ? error.message : "Dashboard overview request failed"
        }
      },
      { status: 500 }
    )
  }
}
