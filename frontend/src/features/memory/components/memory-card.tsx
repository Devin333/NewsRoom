import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { formatDateTime, formatScore, titleCase } from "@/lib/format";
import type { MemoryItem } from "@/types/memory";

export function MemoryCard({ item }: { item: MemoryItem }) {
  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="mb-2 flex flex-wrap gap-2">
              <Badge variant="info">{titleCase(item.type)}</Badge>
              {item.confidence ? <Badge variant={item.confidence === "high" ? "success" : item.confidence === "medium" ? "warning" : "danger"}>{titleCase(item.confidence)}</Badge> : null}
              {item.score !== undefined ? <Badge variant="muted">{formatScore(item.score)}</Badge> : null}
            </div>
            <h2 className="line-clamp-2 text-base font-semibold text-foreground">{item.title}</h2>
          </div>
          <p className="shrink-0 text-xs text-muted-foreground">{formatDateTime(item.createdAt)}</p>
        </div>
        <p className="line-clamp-3 text-sm leading-6 text-muted-foreground">{item.summary}</p>
        <div className="flex flex-wrap gap-2">
          {item.tags.map((tag) => <Badge key={tag} variant="default">{tag}</Badge>)}
        </div>
        {item.relatedObjectIds?.length ? (
          <p className="text-xs text-muted-foreground">
            关联 {titleCase(item.relatedObjectType ?? "objects")}：{item.relatedObjectIds.join(", ")}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
