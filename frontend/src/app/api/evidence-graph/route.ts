import { NextRequest, NextResponse } from "next/server"
import { evidenceGraphQueryFromSearchParams, getEvidenceGraphData } from "@/features/evidence-graph/evidence-graph-data"

export const dynamic = "force-dynamic"

export async function GET(request: NextRequest) {
  try {
    const query = evidenceGraphQueryFromSearchParams(request.nextUrl.searchParams)
    const data = await getEvidenceGraphData(query)
    return NextResponse.json({ success: true, data, error: null })
  } catch (error) {
    return NextResponse.json(
      {
        success: false,
        data: null,
        error: {
          code: "evidence_graph_request_failed",
          message: error instanceof Error ? error.message : "Evidence graph request failed",
        },
      },
      { status: 500 }
    )
  }
}
