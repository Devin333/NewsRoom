import { NextResponse } from "next/server"
import { getPaperTasksResult } from "@/lib/papers/real-data"

export const dynamic = "force-dynamic"

export async function GET() {
  const result = await getPaperTasksResult()
  return NextResponse.json({
    success: true,
    data: {
      tasks: result.items,
      source: result.source,
      dataState: result.dataState,
      notices: result.notices
    }
  })
}
