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
            message: "未找到社区话题。"
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
          message: error instanceof Error ? error.message : "社区话题请求失败"
        }
      },
      { status: 500 }
    )
  }
}
