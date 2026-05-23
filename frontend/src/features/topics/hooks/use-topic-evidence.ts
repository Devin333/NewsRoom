import { evidences, topics } from "@/lib/mock-data";
import type { MockHookResult } from "@/types/common";
import type { Evidence } from "@/types/evidence";

export function useTopicEvidence(topicId: string): MockHookResult<Evidence[]> {
  const topic = topics.find((item) => item.id === topicId);
  return {
    data: topic ? evidences.filter((item) => (topic.evidenceIds ?? []).includes(item.id)) : [],
    isLoading: false,
    isError: false,
    refetch: () => undefined,
  };
}
