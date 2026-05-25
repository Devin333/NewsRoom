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
  "/studio/boards",
  "/studio/evidence",
  "/studio/quality",
  "/studio/review",
  "/studio/artifacts",
  "/studio/sources",
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
  await expect(page.getByRole("button", { name: /^upvote$/i })).toHaveCount(0)
  await expect(page.getByRole("button", { name: /^collection$/i })).toHaveCount(0)
  await expect(page.getByRole("button", { name: /^reading list$/i })).toHaveCount(0)

  const githubHref = await page.locator("a[href^='https://github.com/']").first().getAttribute("href")
  expect(githubHref).toMatch(/^https:\/\/github\.com\/[^/]+\/[^/]+/)
  expect(githubHref).not.toBe("https://github.com/")

  const pdfHref = await page.locator("a[href*='/pdf/'], a[href$='.pdf']").first().getAttribute("href")
  expect(pdfHref).toMatch(/\/pdf\/|\.pdf($|\?)/)
})

test("/papers search, period tabs, and drawer deep-link work", async ({ page }) => {
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
  await page.getByRole("button", { name: /dismiss|关闭/i }).click()
  await expect(page).toHaveURL(/\/papers$/)
})

test("/papers domain links open task detail view", async ({ page }) => {
  await page.goto("/papers")

  await page.locator("a[href='/papers/tasks/agents']").first().click()

  await expect(page).toHaveURL(/\/papers\/tasks\/agents$/)
  await expect(page.locator("nav[aria-label='Papers breadcrumb']")).toContainText("Tasks")
  await expect(page.locator("h1")).toBeVisible()
  await expect(page.locator("aside a[href^='/papers/tasks/']").first()).toBeVisible()
  await expect(page.locator("aside a[href^='/papers/methods/']").first()).toBeVisible()
})
