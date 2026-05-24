import { expect, test } from "@playwright/test"

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
  "/reports",
  "/reports/report-daily-ai-runtime",
  "/search?q=agent&type=topic",
  "/studio",
  "/studio/runs",
  "/studio/runs/run-daily-20260522-0800",
  "/studio/runs/not-found-run",
  "/studio/sources",
  "/studio/memory",
  "/studio/quality",
  "/studio/artifacts",
  "/admin",
]

for (const route of routes) {
  test(`${route} is reachable`, async ({ page }) => {
    const response = await page.goto(route)
    expect(response?.ok()).toBeTruthy()
    await expect(page.locator("body")).toBeVisible()
  })
}

test("/papers uses one breadcrumb and real paper actions", async ({ page }) => {
  await page.goto("/papers")

  await expect(page.locator("nav[aria-label='Papers breadcrumb']")).toHaveCount(1)
  await expect(page.getByText("stars / hr")).toHaveCount(0)

  const githubHref = await page.locator("a[href^='https://github.com/']").first().getAttribute("href")
  expect(githubHref).toMatch(/^https:\/\/github\.com\/[^/]+\/[^/]+/)
  expect(githubHref).not.toBe("https://github.com/")

  const pdfHref = await page.locator("a[href*='/pdf/'], a[href$='.pdf']").first().getAttribute("href")
  expect(pdfHref).toMatch(/\/pdf\/|\.pdf($|\?)/)
})
