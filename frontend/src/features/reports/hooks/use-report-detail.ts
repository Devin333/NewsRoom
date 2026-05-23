import { evidences, newsItems, reports, topics } from "@/lib/mock-data";
import type { Evidence } from "@/types/evidence";
import type { MockHookResult } from "@/types/common";
import type { NewsItem } from "@/types/news";
import type { Report } from "@/types/report";
import type { Topic } from "@/types/topic";

export type ReportDetailData = {
  report?: Report;
  relatedTopics: Topic[];
  relatedNews: NewsItem[];
  evidence: Evidence[];
};

export function useReportDetail(id: string): MockHookResult<ReportDetailData> {
  const report = reports.find((item) => item.id === id);
  return {
    data: {
      report,
      relatedTopics: report ? topics.filter((topic) => (report.topicIds ?? []).includes(topic.id)) : [],
      relatedNews: report ? newsItems.filter((item) => (report.newsItemIds ?? []).includes(item.id)) : [],
      evidence: report ? evidences.filter((item) => report.evidenceIds?.includes(item.id)) : [],
    },
    isLoading: false,
    isError: false,
    refetch: () => undefined,
  };
}
