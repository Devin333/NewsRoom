import { expect, test, type Page } from "@playwright/test"

const widths = [320, 375, 414, 768, 1024, 1280, 1440]

test("Projects Lab remains usable without horizontal overflow across supported viewports", async ({ page, baseURL }, testInfo) => {
  await authenticate(page, baseURL)
  await mockProjectsLab(page)

  for (const width of widths) {
    await test.step(`${width}px`, async () => {
      await page.setViewportSize({ width, height: 900 })
      await page.goto("/projects/lab")

      await expect(page.getByRole("heading", { name: "Lab", exact: true })).toBeVisible()
      await expect(page.getByLabel("Projects Lab workspace")).toBeVisible()
      await expect(page.getByRole("heading", { name: "Start Lab Session" })).toBeVisible()
      if (width < 1280) {
        await expect(page.getByRole("button", { name: "Open Research navigation" })).toBeVisible()
      } else {
        await expect(page.getByRole("navigation", { name: "Portal modules" })).toBeVisible()
      }
      const overflowing = await page.locator("body *").evaluateAll((elements) =>
        elements
          .filter((element) => element.getBoundingClientRect().right > window.innerWidth + 1)
          .map((element) => ({
            tag: element.tagName,
            className: element.getAttribute("class"),
            right: Math.round(element.getBoundingClientRect().right),
          }))
      )
      expect(overflowing).toEqual([])

      await testInfo.attach(`projects-lab-${width}px`, {
        body: await page.screenshot({ fullPage: true }),
        contentType: "image/png",
      })
    })
  }
})

async function authenticate(page: Page, baseURL: string | undefined) {
  await page.addInitScript(() => {
    window.localStorage.setItem(
      "newsroom-ui",
      JSON.stringify({
        state: { sidebarCollapsed: false, rightPanelOpen: true, theme: "light", locale: "en" },
        version: 0,
      })
    )
  })
  await page.route("**/api/auth/session", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ success: true, data: { session: { userId: "e2e-user", username: "e2e", role: "admin" } } }),
    })
  })
  await page.context().addCookies([{ name: "newsroom_session", value: "session-token", url: baseURL ?? "http://127.0.0.1:3000" }])
}

async function mockProjectsLab(page: Page) {
  await page.route(/\/api\/v1\/projects(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          hot: [{
            id: "project-1",
            slug: "project-1",
            name: "Research Workflow Toolkit",
            description: "A real Project Radar record used by the Lab viewport test.",
            project_type: "tool",
            tags: ["workflow"],
            source_confidence: 0.9,
            source_count: 3,
          }],
          rising: [],
          tools: [],
          cases: [
            { id: "case-1", project_id: "project-1", title: "Requirements workflow", business_domain: "research", module_type: "workflow" },
            { id: "case-2", project_id: "project-1", title: "Evidence workflow", business_domain: "research", module_type: "rag" },
            { id: "case-3", project_id: "project-1", title: "Review workflow", business_domain: "research", module_type: "evaluation" },
          ],
          collections: [],
          watchlist: [],
          recommendations: [],
          meta: { source: "artifact", source_run_id: "run-e2e", data_state: "ready", notices: [] },
          metrics: [],
        },
      }),
    })
  })
}
