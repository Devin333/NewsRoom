import { expect, test, type Page } from "@playwright/test"

const routes = [
  "/",
  "/news",
  "/news/news-1-a",
  "/papers",
  "/papers/tasks",
  "/papers/tasks/agents",
  "/papers/methods",
  "/papers/methods/react",
  "/topics",
  "/topics/agent-runtime-observability",
  "/tech",
  "/tech/papers",
  "/tech/repos",
  "/tech/frameworks",
  "/community",
  "/topics?view=evidence-graph",
  "/reports",
  "/reports/report-daily-ai-runtime",
  "/search?q=agent&type=topic",
  "/studio",
  "/studio/runs",
  "/studio/runs/run-daily-20260522-0800",
  "/studio/runs/not-found-run",
  "/studio/boards",
  "/studio/evidence",
  "/studio/quality",
  "/studio/review",
  "/studio/artifacts",
  "/studio/sources",
  "/admin",
]

for (const route of routes) {
  test(`${route} is reachable`, async ({ page, baseURL }) => {
    if (route !== "/") {
      await authenticate(page, baseURL)
    }

    const response = await page.goto(route)
    expect(response?.ok()).toBeTruthy()
    await expect(page.locator("body")).toBeVisible()
  })
}

test("/ renders the Portal homepage modules", async ({ page }) => {
  await useEnglishLocale(page)
  await page.goto("/")

  await expect(page.getByRole("heading", { name: /AI intelligence front page/i })).toBeVisible()
  const modules = page.getByRole("region", { name: "Portal modules" })
  await expect(modules.getByRole("link", { name: /View AI News/i })).toBeVisible()
  await expect(modules.getByRole("link", { name: /View Project Radar/i })).toBeVisible()
  await expect(modules.getByRole("link", { name: /View Paper Radar/i })).toBeVisible()
  await expect(modules.getByRole("link", { name: /View Community Pulse/i })).toBeVisible()
  await expect(modules.getByRole("link", { name: /View Cross-board Evidence Graph/i })).toBeVisible()
  await expect(modules.getByRole("link", { name: /View Reports \/ Briefings/i })).toBeVisible()
  const researchEntries = page.getByRole("region", { name: "Paper Radar research entries" })
  await expect(researchEntries.getByRole("link", { name: /Trending Papers/i })).toHaveAttribute("href", "/papers")
  await expect(researchEntries.getByRole("link", { name: /Tasks/i })).toHaveAttribute("href", "/papers/tasks")
  await expect(researchEntries.getByRole("link", { name: /Methods/i })).toHaveAttribute("href", "/papers/methods")
  await expect(page.locator("body")).not.toContainText("Quality Gate")
})

test("/papers uses one breadcrumb and real paper actions", async ({ page, baseURL }) => {
  await authenticate(page, baseURL)
  await page.goto("/papers")

  await expect(page.locator("nav[aria-label='Papers breadcrumb']")).toHaveCount(1)
  await expect(page.getByText("stars / hr")).toHaveCount(0)
  await expect(page.getByRole("button", { name: /^upvote$/i })).toHaveCount(0)
  await expect(page.getByRole("button", { name: /^collection$/i })).toHaveCount(0)
  await expect(page.getByRole("button", { name: /^reading list$/i })).toHaveCount(0)

  const githubHref = await page.locator("a[href^='https://github.com/']").first().getAttribute("href")
  expect(githubHref).toMatch(/^https:\/\/github\.com\/[^/]+\/[^/]+/)
  expect(githubHref).not.toBe("https://github.com/")

  const pdfHref = await page.locator("a[href*='/pdf/'], a[href$='.pdf']").first().getAttribute("href")
  expect(pdfHref).toMatch(/\/pdf\/|\.pdf($|\?)/)
})

test("/papers search, period tabs, and drawer deep-link work", async ({ page, baseURL }) => {
  await authenticate(page, baseURL)
  await page.goto("/papers")

  const main = page.locator("main")
  await main.locator("[aria-label='Paper period'] button").nth(1).click()
  await expect(page).toHaveURL(/period=weekly/)

  await main.getByRole("textbox").last().fill("agent")
  await main.locator("form button[type='submit']").click()
  await expect(page).toHaveURL(/q=agent/)

  await page.goto("/papers?paper=arxiv-2605.22823")
  await expect(page.getByRole("dialog", { name: /paper detail/i })).toBeVisible()
  await expect(page.getByRole("heading", { name: "NewsRoom AI" })).toBeVisible()
  await expect(page.getByRole("heading", { name: "News and sources" })).toBeVisible()
  await expect(page.getByRole("heading", { name: "Community signals" })).toBeVisible()
  await expect(page.getByRole("heading", { name: "Evidence references" })).toBeVisible()
  await page.getByRole("button", { name: /dismiss|关闭/i }).click()
  await expect(page).toHaveURL(/\/papers$/)
})

test("/papers domain links open task detail view", async ({ page, baseURL }) => {
  await authenticate(page, baseURL)
  await page.goto("/papers")

  await page.locator("a[href='/papers/tasks/agents']").first().click()

  await expect(page).toHaveURL(/\/papers\/tasks\/agents$/)
  await expect(page.locator("nav[aria-label='Papers breadcrumb']")).toContainText("Tasks")
  await expect(page.locator("h1")).toBeVisible()
  await expect(page.locator("aside a[href^='/papers/tasks/']").first()).toBeVisible()
  await expect(page.locator("aside a[href^='/papers/methods/']").first()).toBeVisible()
})

test("/tech/repos opens a Project Radar detail drawer from URL", async ({ page, baseURL }) => {
  await authenticate(page, baseURL)
  await mockProjectRadar(page)

  await page.goto("/tech/repos?project=openai-codex")

  await expect(page.getByRole("heading", { name: /Project Radar Board/i })).toBeVisible()
  const drawer = page.getByRole("dialog", { name: /project detail/i })
  await expect(drawer).toBeVisible()
  await expect(drawer.getByRole("heading", { name: "codex" })).toBeVisible()
  await expect(drawer.getByRole("link", { name: /open repo/i })).toHaveAttribute("href", "https://github.com/openai/codex")

  await page.getByRole("button", { name: /close project detail/i }).click()
  await expect(page).toHaveURL(/\/tech\/repos$/)
})

test("/topics evidence graph renders the structured PRD-07 surface", async ({ page, baseURL }) => {
  await authenticate(page, baseURL)
  await page.goto("/topics?view=evidence-graph&topic=Agent")

  await expect(page.getByRole("heading", { name: "Cross-board Evidence Graph" })).toBeVisible()
  await expect(page.getByLabel("搜索主题")).toBeVisible()
  await expect(page.getByText("Graph Summary")).toBeVisible()
  await expect(page.getByText("Signal Mix")).toBeVisible()
  await expect(page.getByText("Evidence Chain")).toBeVisible()
  await expect(page.getByText("Timeline")).toBeVisible()
  await expect(page.getByText("Evidence Inspector")).toBeVisible()
  await expect(page.getByText("Related Reports")).toBeVisible()
})

async function authenticate(page: Page, baseURL: string | undefined) {
  await useEnglishLocale(page)
  await page.route("**/api/auth/session", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          session: {
            userId: "e2e-user",
            username: "e2e",
            role: "admin"
          }
        }
      })
    })
  })
  await page.context().addCookies([
    {
      name: "newsroom_session",
      value: "session-token",
      url: baseURL ?? "http://127.0.0.1:3000"
    }
  ])
}

async function useEnglishLocale(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem(
      "newsroom-ui",
      JSON.stringify({
        state: {
          sidebarCollapsed: false,
          rightPanelOpen: true,
          theme: "light",
          locale: "en"
        },
        version: 0
      })
    )
  })
}

async function mockProjectRadar(page: Page) {
  const project = {
    id: "codex",
    slug: "openai-codex",
    name: "codex",
    fullName: "openai/codex",
    description: "A coding agent that runs in your terminal.",
    repoUrl: "https://github.com/openai/codex",
    owner: "openai",
    language: "TypeScript",
    stars: 12000,
    forks: 500,
    openIssues: 42,
    starGrowth7d: 320,
    scores: { trendScore: 88, activityScore: 60, evidenceScore: 2 },
    categoryRefs: [{ category: "agent_framework", label: "Agent Framework" }],
    categories: ["agent_framework"],
    tags: ["devtool"],
    topics: ["Agent Framework", "devtool"],
    maturity: "rising",
    relationCounts: { papers: 0, news: 1, community: 1 },
    relatedNews: [{ title: "Codex launch", url: "https://example.com/news", sourceName: "Example" }],
    relatedCommunityTopics: [{ title: "HN discussion", url: "https://news.ycombinator.com/item?id=1", sourceName: "Hacker News" }]
  }

  await page.route("**/api/projects/openai-codex", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: { project, dataState: "ready", source: "artifact", notices: [] },
        error: null
      })
    })
  })

  await page.route(/\/api\/projects(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          items: [project],
          allItems: [project],
          allFiltered: [project],
          metrics: [
            { label: "Projects", value: 1 },
            { label: "With stars", value: 1 },
            { label: "Star delta", value: 320 },
            { label: "Active signals", value: 1, hint: "2 related references" }
          ],
          options: {
            categories: [{ value: "agent_framework", label: "Agent Framework", count: 1 }],
            sources: [{ value: "github", label: "GitHub", count: 1 }],
            languages: [{ value: "typescript", label: "TypeScript", count: 1 }],
            topics: [{ value: "Agent Framework", label: "Agent Framework", count: 1 }],
            maturity: [{ value: "rising", label: "Rising", count: 1 }]
          },
          page: { page: 1, pageSize: 24, total: 1, hasNext: false, nextCursor: null },
          dataState: "ready",
          source: "artifact",
          notices: []
        },
        error: null
      })
    })
  })
}
