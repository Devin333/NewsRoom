"use client"

import { useMemo, useState } from "react"
import type { StudioReviewItem } from "@/types/review"

export type ReviewQueueFilter = "all" | "pending" | "high-risk" | "blocked" | "history"

export function useReviewQueue(items: StudioReviewItem[]) {
  const [filter, setFilter] = useState<ReviewQueueFilter>("pending")
  const [query, setQuery] = useState("")

  const metrics = useMemo(() => reviewQueueMetrics(items), [items])
  const filteredItems = useMemo(() => filterReviewItems(items, filter, query), [items, filter, query])

  return {
    filter,
    setFilter,
    query,
    setQuery,
    metrics,
    filteredItems
  }
}

export function reviewQueueMetrics(items: StudioReviewItem[]) {
  return {
    all: items.length,
    pending: items.filter((item) => item.status === "pending").length,
    highRisk: items.filter((item) => item.riskLevel === "high" || item.riskLevel === "critical").length,
    blocked: items.filter((item) => item.source === "run").length,
    history: items.filter((item) => item.status !== "pending").length
  }
}

export function filterReviewItems(items: StudioReviewItem[], filter: ReviewQueueFilter, query: string): StudioReviewItem[] {
  const normalizedQuery = query.trim().toLowerCase()
  return items.filter((item) => {
    const matchesFilter =
      filter === "all" ||
      (filter === "pending" && item.status === "pending") ||
      (filter === "high-risk" && (item.riskLevel === "high" || item.riskLevel === "critical")) ||
      (filter === "blocked" && item.source === "run") ||
      (filter === "history" && item.status !== "pending")

    if (!matchesFilter) return false
    if (!normalizedQuery) return true

    return [
      item.approvalId,
      item.requestedAction,
      item.status,
      item.riskLevel,
      item.runId,
      item.reportId,
      item.requestedBy,
      item.reason
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase()
      .includes(normalizedQuery)
  })
}
