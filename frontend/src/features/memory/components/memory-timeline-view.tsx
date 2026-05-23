import { Badge } from "@/components/ui/badge";
import { formatDateTime, titleCase } from "@/lib/format";
import type { MemoryItem } from "@/types/memory";

export function MemoryTimelineView({ items }: { items: MemoryItem[] }) {
  const sorted = [...items].sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());
  return (
    <div className="space-y-3">
      {sorted.map((item) => (
        <div key={item.id} className="grid gap-3 rounded-lg border border-border bg-card p-4 sm:grid-cols-[10rem_minmax(0,1fr)]">
          <p className="text-sm text-muted-foreground">{formatDateTime(item.createdAt)}</p>
          <div>
            <Badge variant="info">{titleCase(item.type)}</Badge>
            <h3 className="mt-2 font-semibold text-foreground">{item.title}</h3>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">{item.summary}</p>
          </div>
        </div>
      ))}
    </div>
  );
}
