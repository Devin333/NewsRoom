"use client";

import { useMemo, useState } from "react";
import { qualityResults } from "@/lib/mock-data";
import type { QualityFilters, QualityResult } from "@/types/quality";

const initialFilters: QualityFilters = {
  keyword: "",
  objectType: "all",
  status: "all",
  minScore: 0,
  review: "all",
};

export function useQualityResults() {
  const [filters, setFilters] = useState<QualityFilters>(initialFilters);
  const [selectedResultId, setSelectedResultId] = useState(qualityResults[0]?.id);

  const results = useMemo(() => {
    return filterQualityResults(qualityResults, filters);
  }, [filters]);

  return {
    allResults: qualityResults,
    results,
    filters,
    setFilters,
    selectedResult: results.find((result) => result.id === selectedResultId) ?? results[0],
    setSelectedResultId,
  };
}

export function filterQualityResults(results: QualityResult[], filters: QualityFilters) {
  const keyword = filters.keyword.trim().toLowerCase();
  return results.filter((result) => {
    const matchesKeyword = !keyword || [result.objectTitle, result.objectId, result.status, result.objectType].join(" ").toLowerCase().includes(keyword);
    const matchesType = filters.objectType === "all" || result.objectType === filters.objectType;
    const matchesStatus = filters.status === "all" || result.status === filters.status;
    const matchesScore = result.score >= filters.minScore;
    const matchesReview =
      filters.review === "all" ||
      (filters.review === "pending" && result.reviewerDecision === "pending") ||
      (filters.review === "decided" && result.reviewerDecision !== undefined && result.reviewerDecision !== "pending");
    return matchesKeyword && matchesType && matchesStatus && matchesScore && matchesReview;
  });
}
