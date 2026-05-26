import { translate } from "@/lib/i18n"
import type { TranslationKey } from "@/lib/i18n/translations"
import type { LocaleMode } from "@/stores/ui-store"

const navigationKeyByLabel: Record<string, TranslationKey> = {
  Today: "nav.today",
  "Top Stories": "nav.topStories",
  "Official Updates": "nav.officialUpdates",
  "Product Updates": "nav.productUpdates",
  "Open Source": "nav.openSource",
  "Community Buzz": "nav.communityBuzz",
  Saved: "nav.saved",
  Trends: "nav.trends",
  Hot: "nav.hot",
  Rising: "nav.rising",
  Timeline: "nav.timeline",
  Controversial: "nav.controversial",
  "Evidence Graph": "nav.evidenceGraph",
  Compare: "nav.compare",
  Topics: "nav.topics",
  Agents: "nav.agents",
  LLMs: "nav.llms",
  Models: "nav.models",
  Frameworks: "nav.frameworks",
  Engineering: "nav.engineering",
  "AI Products": "nav.aiProducts",
  Companies: "nav.companies",
  Research: "nav.research",
  Papers: "nav.papers",
  "Trending Papers": "nav.trendingPapers",
  Tasks: "nav.tasks",
  Methods: "nav.methods",
  Benchmarks: "nav.benchmarks",
  "Papers with Code": "nav.papersWithCode",
  Institutions: "nav.institutions",
  "Reading List": "nav.readingList",
  "Paper Digests": "nav.paperDigests",
  Reports: "nav.reports",
  Daily: "nav.daily",
  Weekly: "nav.weekly",
  "Deep Dives": "nav.deepDives",
  Briefings: "nav.briefings",
  Watchlists: "nav.watchlists",
  Archive: "nav.archive",
  Studio: "nav.studio",
  Runs: "nav.runs",
  Sources: "nav.sources",
  Workflows: "nav.workflows",
  Memory: "nav.memory",
  Evaluation: "nav.evaluation",
  Subscriptions: "nav.subscriptions",
  Settings: "nav.settings"
}

export function navigationLabel(label: string, locale: LocaleMode): string {
  const key = navigationKeyByLabel[label]
  return key ? translate(locale, key) : label
}
