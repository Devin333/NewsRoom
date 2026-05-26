"use client"

import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import { EmptyState } from "@/components/common/empty-state"
import { ErrorState } from "@/components/common/error-state"
import { PageSkeleton } from "@/components/common/loading-skeleton"
import { CommunityTopicDetail } from "@/features/community/components/community-topic-detail"
import { fetchCommunityTopic } from "@/lib/community/api"

export default function CommunityTopicPage({ params }: { params: { slug: string } }) {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["community", "topic", params.slug],
    queryFn: () => fetchCommunityTopic(params.slug)
  })

  if (isLoading) return <PageSkeleton />

  if (isError && typeof error === "object" && error !== null && "code" in error && error.code === "community_topic_not_found") {
    return (
      <EmptyState
        title="Topic not found"
        description="This Community Pulse topic is not available in the current public artifact."
        action={
          <Link href="/community" className="rounded-md border border-border px-3 py-2 text-sm text-foreground hover:bg-secondary">
            Back to Community Pulse
          </Link>
        }
      />
    )
  }

  if (isError) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "Community topic failed to load."}
        onRetry={() => refetch()}
      />
    )
  }

  if (!data) {
    return (
      <EmptyState
        title="Topic not found"
        description="This Community Pulse topic is not available in the current public artifact."
        action={
          <Link href="/community" className="rounded-md border border-border px-3 py-2 text-sm text-foreground hover:bg-secondary">
            Back to Community Pulse
          </Link>
        }
      />
    )
  }

  return <CommunityTopicDetail topic={data} />
}
