export type NavigationChild = {
  label: string
  href: string
  description?: string
}

export type NavigationItem = {
  label: string
  href: string
  children: NavigationChild[]
}

export const NAVIGATION: NavigationItem[] = [
  {
    label: "Today",
    href: "/",
    children: [
      { label: "Top Stories", href: "/#top-stories" },
      { label: "Official Updates", href: "/news?source=official" },
      { label: "Product Updates", href: "/news?topic=product-updates" },
      { label: "Open Source", href: "/tech/repos" },
      { label: "Community Buzz", href: "/news?source=community" },
      { label: "Saved", href: "/search?filter=saved" }
    ]
  },
  {
    label: "Trends",
    href: "/?view=trends",
    children: [
      { label: "Hot", href: "/?view=trends&sort=hot" },
      { label: "Rising", href: "/?view=trends&sort=rising" },
      { label: "Timeline", href: "/topics?view=timeline" },
      { label: "Controversial", href: "/news?sort=controversial" },
      { label: "Evidence Graph", href: "/topics?view=evidence-graph" },
      { label: "Compare", href: "/topics?view=compare" }
    ]
  },
  {
    label: "Topics",
    href: "/topics",
    children: [
      { label: "Agents", href: "/topics?topic=agents" },
      { label: "LLMs", href: "/topics?topic=llms" },
      { label: "Models", href: "/topics?topic=models" },
      { label: "Open Source", href: "/topics?topic=open-source" },
      { label: "Frameworks", href: "/topics?topic=frameworks" },
      { label: "Engineering", href: "/topics?topic=engineering" },
      { label: "AI Products", href: "/topics?topic=ai-products" },
      { label: "Companies", href: "/topics?topic=companies" }
    ]
  },
  {
    label: "Research",
    href: "/tech/papers",
    children: [
      { label: "Papers", href: "/tech/papers" },
      { label: "Benchmarks", href: "/tech?type=benchmarks" },
      { label: "Papers with Code", href: "/tech/repos?type=papers-with-code" },
      { label: "Institutions", href: "/tech?type=institutions" },
      { label: "Reading List", href: "/search?type=reading-list" },
      { label: "Paper Digests", href: "/reports?type=paper-digests" }
    ]
  },
  {
    label: "Reports",
    href: "/reports",
    children: [
      { label: "Daily", href: "/reports?type=daily" },
      { label: "Weekly", href: "/reports?type=weekly" },
      { label: "Deep Dives", href: "/reports?type=deep-dives" },
      { label: "Briefings", href: "/reports?type=briefings" },
      { label: "Watchlists", href: "/reports?type=watchlists" },
      { label: "Archive", href: "/reports?type=archive" }
    ]
  },
  {
    label: "Studio",
    href: "/studio",
    children: [
      { label: "Runs", href: "/studio/runs" },
      { label: "Sources", href: "/studio/sources" },
      { label: "Workflows", href: "/studio/runs?view=workflows" },
      { label: "Agents", href: "/studio/runs?view=agents" },
      { label: "Memory", href: "/studio/memory" },
      { label: "Evaluation", href: "/studio/quality" },
      { label: "Subscriptions", href: "/studio/sources?view=subscriptions" },
      { label: "Settings", href: "/studio?view=settings" }
    ]
  }
]
