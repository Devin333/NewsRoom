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

export const PORTAL_NAVIGATION: NavigationItem[] = [
  {
    label: "Papers",
    href: "/papers",
    children: [
      { label: "Trending Papers", href: "/papers" },
      { label: "Tasks", href: "/papers/tasks" },
      { label: "Methods", href: "/papers/methods" }
    ]
  },
  {
    label: "Today",
    href: "/news",
    children: [
      { label: "Top Stories", href: "/news" },
      { label: "Official Updates", href: "/news?source=official" },
      { label: "Product Updates", href: "/news?topic=product-updates" },
      { label: "Open Source", href: "/tech/repos" },
      { label: "Community Pulse", href: "/community" }
    ]
  },
  {
    label: "Trends",
    href: "/topics",
    children: [
      { label: "Hot", href: "/news?sort=hot" },
      { label: "Rising", href: "/news?sort=rising" },
      { label: "Timeline", href: "/topics?view=timeline" },
      { label: "Controversial", href: "/news?sort=controversial" },
      { label: "Evidence Graph", href: "/topics?view=evidence-graph" },
      { label: "Agents", href: "/topics?topic=agents" },
      { label: "LLMs", href: "/topics?topic=llms" },
      { label: "Models", href: "/topics?topic=models" },
      { label: "Compare", href: "/topics?view=compare" }
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
  }
]

export const NAVIGATION = PORTAL_NAVIGATION
