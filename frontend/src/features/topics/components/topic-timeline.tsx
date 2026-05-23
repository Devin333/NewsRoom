"use client";

import { useState } from "react";
import Link from "next/link";
import { Badge } from "@/components/common/badges";
import { EmptyState } from "@/components/common/empty-state";
import { evidences } from "@/lib/mock-data";
import { formatDateTime } from "@/lib/format";
import type { TopicTimelineItem } from "@/types/topic";

export function TopicTimeline({ items }: { items: TopicTimelineItem[] }) {
  const [expanded, setExpanded] = useState<string>();
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const sorted = [...items].sort((a, b) => {
    const diff = new Date(a.occurredAt).getTime() - new Date(b.occurredAt).getTime();
    return order === "asc" ? diff : -diff;
  });

  if (!items.length) {
    return <EmptyState title="暂无时间线" description="这个主题还没有积累足够的事件历史。" />;
  }

  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-foreground">时间线</h2>
        <button className="rounded-md border border-border px-3 py-1.5 text-xs text-muted-foreground" onClick={() => setOrder(order === "asc" ? "desc" : "asc")}>
          {order === "asc" ? "最早优先" : "最新优先"}
        </button>
      </div>
      <div className="mt-4 space-y-3">
        {sorted.map((item) => {
          const open = expanded === item.id;
          const relatedEvidence = evidences.filter((evidence) => item.evidenceIds.includes(evidence.id));
          return (
            <div key={item.id} className="rounded-lg border border-border bg-background/50 p-4">
              <button className="w-full text-left" onClick={() => setExpanded(open ? undefined : item.id)}>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-foreground">{item.title}</p>
                    <p className="mt-1 text-xs text-muted-foreground">{formatDateTime(item.occurredAt)} · {item.sourceCount} 个来源</p>
                  </div>
                  <div className="flex gap-2">
                    <Badge tone={item.importance === "high" ? "good" : item.importance === "medium" ? "info" : "neutral"}>{item.importance}</Badge>
                    <Badge>{item.type}</Badge>
                  </div>
                </div>
                <p className="mt-3 text-sm leading-6 text-muted-foreground">{item.summary}</p>
              </button>
              {open ? (
                <div className="mt-3 space-y-2 border-t border-border pt-3">
                  {relatedEvidence.map((evidence) => (
                    <p key={evidence.id} className="rounded-md bg-secondary p-3 text-xs text-muted-foreground">{evidence.title}: {evidence.summary}</p>
                  ))}
                  {item.relatedNewsId ? <Link className="text-sm text-primary hover:underline" href={`/search?type=news&q=${item.relatedNewsId}`}>打开相关新闻</Link> : null}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </section>
  );
}
