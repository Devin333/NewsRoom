export const queryKeys = {
  dashboard: ["dashboard"] as const,
  news: {
    all: ["news"] as const,
    list: (filters: unknown) => ["news", "list", filters] as const,
    detail: (id: string) => ["news", id] as const
  },
  topics: {
    all: ["topics"] as const,
    detail: (id: string) => ["topics", id] as const
  },
  reports: {
    all: ["reports"] as const,
    detail: (id: string) => ["reports", id] as const
  },
  studio: {
    runs: ["studio", "runs"] as const,
    runDetail: (id: string) => ["studio", "runs", id] as const,
    pdfProxyStats: (windowHours: number) => ["studio", "paper-reader", "pdf-proxy", "stats", windowHours] as const,
    sources: ["studio", "sources"] as const,
    sourcePreview: (id: string) => ["studio", "sources", id, "preview"] as const
  }
}
