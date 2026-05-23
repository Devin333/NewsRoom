import type { TopicFilters } from "@/types/topic";

export function TopicFilterPanel({ filters }: { filters: TopicFilters }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">
      Active filters: {Object.values(filters).filter(Boolean).length || "none"}
    </div>
  );
}
