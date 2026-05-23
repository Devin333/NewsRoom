export type SearchObjectType =
  | "news"
  | "topic"
  | "report"
  | "evidence"
  | "tech"
  | "memory"
  | "source"
  | "agent_run";

export type SearchResult = {
  id: string;
  objectType: SearchObjectType;
  title: string;
  summary?: string;
  matchedSnippet?: string;
  timestamp?: string;
  tags?: string[];
  sourceName?: string;
  relevanceScore?: number;
  href: string;
};
