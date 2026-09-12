import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

for (const theme of ["light", "dark"]) {
  test(`remaining screens fit the viewport and meet axe AA in ${theme} theme`, async ({ page }) => {
    await page.addInitScript((value) => localStorage.setItem("m-ranked-theme", value), theme);
    await page.setExtraHTTPHeaders({ authorization: `Basic ${Buffer.from("admin:fixture-password").toString("base64")}` });
    for (const path of ["/rating?platform=telegram", "/accounts/00000001-0000-4000-8000-000000000001", "/compare?platform=max", "/missing-page", "/manage"]) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
    }
  });
}

for (const path of ["/compare?platform=vk", "/posts/1"]) {
  test(`${path} controls work while the SVG runtime is still downloading`, async ({ page }) => {
    let release: (() => void) | undefined;
    const pending = new Promise<void>(resolve => { release = resolve; });
    let delayed = false;
    await page.route("**/_next/static/chunks/*.js", async route => {
      const response = await route.fetch();
      const body = await response.text();
      if (body.includes("recharts-wrapper")) {
        delayed = true;
        await pending;
      }
      await route.fulfill({ response, body });
    });
    try {
      await page.goto(path, { waitUntil: "domcontentloaded" });
      const control = path.startsWith("/compare")
        ? page.getByTestId("comparison-legend-toggle").first()
        : page.getByRole("button", { name: "Авто", exact: true }).first();
      await control.click();
      await expect(control).toHaveAttribute("aria-pressed", path.startsWith("/compare") ? "false" : "true");
      await expect.poll(() => delayed).toBe(true);
      await expect(page.locator("svg.recharts-surface")).toHaveCount(0);
      release!();
      await expect(page.locator('[data-chart-ready="true"] svg.recharts-surface')).toHaveCount(2);
      await expect(control).toHaveAttribute("aria-pressed", path.startsWith("/compare") ? "false" : "true");
    } finally { release?.(); }
  });
}

test("keyboard skip link becomes visible and focuses the main content", async ({ page }) => {
  await page.goto("/rating?platform=telegram");
  await page.getByRole("heading", { level: 1 }).waitFor();
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "Перейти к содержимому" });
  await expect(skip).toBeFocused();
  await expect(skip).toBeInViewport();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("main")).toBeFocused();
});
