"use client";

import { useMemo, useState } from "react";
import { artifacts } from "@/lib/mock-data";
import type { Artifact, ArtifactFilters } from "@/types/artifact";

const initialFilters: ArtifactFilters = {
  keyword: "",
  artifactType: "all",
  runId: "",
};

export function useArtifacts() {
  const [filters, setFilters] = useState<ArtifactFilters>(initialFilters);
  const [selectedArtifactId, setSelectedArtifactId] = useState(artifacts[0]?.id);

  const filteredArtifacts = useMemo(() => {
    return filterArtifacts(artifacts, filters);
  }, [filters]);

  return {
    artifacts: filteredArtifacts,
    allArtifacts: artifacts,
    filters,
    setFilters,
    selectedArtifact: filteredArtifacts.find((artifact) => artifact.id === selectedArtifactId) ?? filteredArtifacts[0],
    setSelectedArtifactId,
  };
}

export function filterArtifacts(items: Artifact[], filters: ArtifactFilters) {
  const keyword = filters.keyword.trim().toLowerCase();
  return items.filter((artifact) => {
    const matchesKeyword = !keyword || [artifact.filename, artifact.id, artifact.runId, artifact.stepId, artifact.artifactType].join(" ").toLowerCase().includes(keyword);
    const matchesType = filters.artifactType === "all" || artifact.artifactType === filters.artifactType;
    const matchesRun = !filters.runId || artifact.runId?.toLowerCase().includes(filters.runId.toLowerCase());
    return matchesKeyword && matchesType && matchesRun;
  });
}

export function artifactTypeCounts(items: Artifact[]) {
  return items.reduce<Record<string, number>>((counts, artifact) => {
    counts[artifact.artifactType] = (counts[artifact.artifactType] ?? 0) + 1;
    return counts;
  }, {});
}
