import { evidences, newsItems, techItems, topics } from "@/lib/mock-data";
import type { Evidence } from "@/types/evidence";
import type { MockHookResult } from "@/types/common";
import type { NewsItem } from "@/types/news";
import type { TechItem } from "@/types/tech";
import type { Topic } from "@/types/topic";

export type TopicDetailData = {
  topic?: Topic;
  evidence: Evidence[];
  relatedNews: NewsItem[];
  relatedTech: TechItem[];
};

export function useTopicDetail(id: string): MockHookResult<TopicDetailData> {
  const topic = topics.find((item) => item.id === id);
  return {
    data: {
      topic,
      evidence: topic ? evidences.filter((item) => (topic.evidenceIds ?? []).includes(item.id)) : [],
      relatedNews: topic ? newsItems.filter((item) => (topic.relatedNewsIds ?? []).includes(item.id)) : [],
      relatedTech: topic ? techItems.filter((item) => (topic.relatedTechItemIds ?? []).includes(item.id)) : [],
    },
    isLoading: false,
    isError: false,
    refetch: () => undefined,
  };
}
