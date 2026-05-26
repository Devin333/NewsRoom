import { NextResponse } from "next/server"
import { getPaperMethodsResult } from "@/lib/papers/real-data"

export const dynamic = "force-dynamic"

export async function GET() {
  const result = await getPaperMethodsResult()
  return NextResponse.json({
    success: true,
    data: {
      methods: result.items,
      source: result.source,
      dataState: result.dataState,
      notices: result.notices
    }
  })
}
