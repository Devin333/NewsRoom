"use client"

import { useQuery } from "@tanstack/react-query"
import { getEvidenceForNews, mockNews, mockReports, mockTopics } from "@/lib/api/mock-data"
import { queryKeys } from "@/lib/query/query-keys"

export function useNewsDetail(id: string) {
  return useQuery({
    queryKey: queryKeys.news.detail(id),
    queryFn: async () => {
      const news = mockNews.find((item) => item.id === id)
      if (!news) {
        return {
          news: undefined,
          evidence: [],
          topic: undefined,
          reports: []
        }
      }
      return {
        news,
        evidence: getEvidenceForNews(news),
        topic: news.topicId ? mockTopics.find((topic) => topic.id === news.topicId) : undefined,
        reports: mockReports.filter((report) => news.reportIds?.includes(report.id))
      }
    }
  })
}
