export type TechItemType = "paper" | "repo" | "framework" | "method" | "practice";

export type TechMaturity = "experimental" | "emerging" | "stable" | "mature";

export type TechItem = {
  id: string;
  name: string;
  type: TechItemType;
  summary: string;
  problem?: string;
  maturity: TechMaturity;
  sourceUrl: string;
  relatedTopicIds?: string[];
  relatedTopicNames?: string[];
  tags: string[];
  agentEvaluation?: string;
  referenceValue?: string;
  createdAt?: string;
  updatedAt?: string;
};
