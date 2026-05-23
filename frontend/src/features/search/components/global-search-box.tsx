"use client";

import { Search } from "lucide-react";

export function GlobalSearchBox({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <label className="flex items-center gap-3 rounded-lg border border-border bg-card px-4 py-3">
      <Search className="h-5 w-5 text-muted-foreground" />
      <input
        className="w-full bg-transparent text-base outline-none placeholder:text-muted-foreground"
        placeholder="搜索新闻、主题、证据、报告、技术、记忆..."
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}
