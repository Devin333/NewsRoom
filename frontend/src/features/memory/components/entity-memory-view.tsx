import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDateTime, formatNumber } from "@/lib/format";
import type { MemoryItem } from "@/types/memory";

export function EntityMemoryView({ items }: { items: MemoryItem[] }) {
  const entities = new Map<string, MemoryItem[]>();
  items.forEach((item) => item.entityNames?.forEach((name) => entities.set(name, [...(entities.get(name) ?? []), item])));

  return (
    <div className="grid gap-4 md:grid-cols-2">
      {[...entities.entries()].map(([entityName, entityItems]) => {
        const topicCount = new Set(entityItems.flatMap((item) => item.topicIds ?? [])).size;
        const latest = [...entityItems].sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())[0];
        return (
          <Card key={entityName}>
            <CardHeader><CardTitle>{entityName}</CardTitle></CardHeader>
            <CardContent className="space-y-2 text-sm text-muted-foreground">
              <p>{formatNumber(entityItems.length)} 条相关记忆</p>
              <p>{formatNumber(topicCount)} 个相关主题</p>
              <p>最近活动 {formatDateTime(latest?.createdAt)}</p>
              <p className="leading-6">{latest?.summary}</p>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
