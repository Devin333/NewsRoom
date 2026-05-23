"use client";

import type { MemoryViewMode } from "@/types/memory";
import { cn } from "@/lib/format";

const tabs: Array<{ id: MemoryViewMode; label: string }> = [
  { id: "list", label: "记忆列表" },
  { id: "evidence", label: "证据" },
  { id: "entity", label: "实体" },
  { id: "topic", label: "主题历史" },
  { id: "timeline", label: "时间线" },
];

export function MemoryViewTabs({ value, onChange }: { value: MemoryViewMode; onChange: (value: MemoryViewMode) => void }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-card p-1">
      <div className="flex min-w-max gap-1">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={cn("rounded-md px-3 py-2 text-sm text-muted-foreground hover:bg-secondary hover:text-foreground", value === tab.id && "bg-secondary text-foreground")}
            onClick={() => onChange(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>
    </div>
  );
}
