"use client";

import { useState } from "react";
import { EvidenceList } from "@/components/common/evidence-list";
import { cn } from "@/lib/format";
import type { Evidence } from "@/types/evidence";
import type { NewsItem } from "@/types/news";
import type { TechItem } from "@/types/tech";
import type { Topic } from "@/types/topic";
import { AgentAnalysisPanel } from "./agent-analysis-panel";
import { SourceMatrix } from "./source-matrix";
import { TopicTimeline } from "./topic-timeline";
import { TechItemCard } from "@/features/tech/components/tech-item-card";

const tabs = ["overview", "timeline", "evidence", "sources", "relatedNews", "agentAnalysis"] as const;
const tabLabels: Record<(typeof tabs)[number], string> = {
  overview: "概览",
  timeline: "时间线",
  evidence: "证据",
  sources: "来源",
  relatedNews: "相关新闻",
  agentAnalysis: "智能体分析",
};

export function TopicDetailTabs({
  topic,
  evidence,
  relatedNews,
  relatedTech,
}: {
  topic: Topic;
  evidence: Evidence[];
  relatedNews: NewsItem[];
  relatedTech: TechItem[];
}) {
  const [active, setActive] = useState<(typeof tabs)[number]>("overview");

  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <div className="flex flex-wrap gap-2 border-b border-border pb-3">
        {tabs.map((tab) => (
          <button
            key={tab}
            className={cn("rounded-md px-3 py-2 text-sm text-muted-foreground hover:bg-secondary hover:text-foreground", active === tab && "bg-secondary text-foreground")}
            onClick={() => setActive(tab)}
          >
            {tabLabels[tab]}
          </button>
        ))}
      </div>
      <div className="mt-4">
        {active === "overview" ? (
          <div className="space-y-4">
            <p className="text-sm leading-7 text-muted-foreground">{topic.executiveSummary ?? topic.summary}</p>
            <div className="grid gap-3 md:grid-cols-2">
              {relatedTech.map((item) => <TechItemCard key={item.id} item={item} compact />)}
            </div>
          </div>
        ) : null}
        {active === "timeline" ? <TopicTimeline items={topic.timeline ?? []} /> : null}
        {active === "evidence" ? <EvidenceList evidence={evidence} /> : null}
        {active === "sources" ? <SourceMatrix sources={topic.sourceCoverage ?? []} /> : null}
        {active === "relatedNews" ? (
          <div className="space-y-3">
            {relatedNews.map((item) => (
              <div key={item.id} className="rounded-md border border-border bg-background/50 p-3">
                <p className="text-sm font-semibold text-foreground">{item.title}</p>
                <p className="mt-1 text-sm text-muted-foreground">{item.summary}</p>
              </div>
            ))}
          </div>
        ) : null}
        {active === "agentAnalysis" ? <AgentAnalysisPanel analyses={topic.agentAnalysis ?? []} /> : null}
      </div>
    </section>
  );
}
