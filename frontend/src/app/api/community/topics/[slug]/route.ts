import { NextRequest, NextResponse } from "next/server"
import { getCommunityTopic } from "@/lib/community/server-data"

export const dynamic = "force-dynamic"

export async function GET(_request: NextRequest, { params }: { params: { slug: string } }) {
  try {
    const topic = await getCommunityTopic(params.slug)
    if (!topic) {
      return NextResponse.json(
        {
          success: false,
          error: {
            code: "community_topic_not_found",
            message: "Community Pulse topic was not found."
          }
        },
        { status: 404 }
      )
    }

    return NextResponse.json({ success: true, data: { topic } })
  } catch (error) {
    return NextResponse.json(
      {
        success: false,
        error: {
          code: "community_topic_request_failed",
          message: error instanceof Error ? error.message : "Community Pulse topic request failed"
        }
      },
      { status: 500 }
    )
  }
}
