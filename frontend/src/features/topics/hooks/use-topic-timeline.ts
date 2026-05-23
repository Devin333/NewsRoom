import { topics } from "@/lib/mock-data";
import type { MockHookResult } from "@/types/common";
import type { TopicTimelineItem } from "@/types/topic";

export function useTopicTimeline(topicId: string, order: "asc" | "desc" = "desc"): MockHookResult<TopicTimelineItem[]> {
  const topic = topics.find((item) => item.id === topicId);
  const timeline = [...(topic?.timeline ?? [])].sort((a, b) => {
    const diff = new Date(a.occurredAt).getTime() - new Date(b.occurredAt).getTime();
    return order === "asc" ? diff : -diff;
  });
  return {
    data: timeline,
    isLoading: false,
    isError: false,
    refetch: () => undefined,
  };
}
