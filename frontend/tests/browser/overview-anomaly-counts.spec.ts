import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test("overview shows severity counts, hides zeroes, and keeps badges clear of the title", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("m-ranked-theme", "dark"));
  await page.goto("/review?platform=vk&period=1d");
  const cards = page.getByTestId("platform-overview-card");
  const card = cards.first();
  const red = card.getByTestId("overview-anomaly-level-3");
  const orange = card.getByTestId("overview-anomaly-level-2");
  await expect(red).toHaveText("1");
  await expect(orange).toHaveText("3");
  await expect(red).toHaveAttribute("aria-label", /Признаки искусственной активности.*ВК/);
  await expect(orange).toHaveAttribute("aria-label", /Выраженная аномалия/);
  await expect(cards.nth(1).getByTestId("overview-anomaly-level-3")).toHaveCount(0);
  await expect(cards.nth(1).getByTestId("overview-anomaly-level-2")).toHaveCount(0);
  await expect(card).toContainText("М‑Рейтинг");
  const status = card.getByTestId("overview-status");
  await expect(status).toContainText("Активен");
  await expect(status.locator("time")).toHaveAttribute("aria-label", /Последний опрос:.*2026.*МСК/);
  const footerLayout = await status.evaluate(element => {
    const [state, time] = Array.from(element.children).map(child => child.getBoundingClientRect());
    return { sameLine: Math.abs(state.y - time.y) < 1, overlap: state.right > time.x, overflow: element.scrollWidth > element.clientWidth };
  });
  expect(footerLayout).toEqual({sameLine:true, overlap:false, overflow:false});
  await expect(card.getByRole("region", {name:"Прирост за сутки",exact:true})).toBeVisible();
  await expect(card.getByRole("region", {name:"Медиана прироста",exact:true})).toBeVisible();
  await card.getByRole("heading", {level:3}).waitFor();
  const redBounds = await red.boundingBox(), orangeBounds = await orange.boundingBox();
  const titleBounds = await card.getByRole("heading", {level:3}).boundingBox();
  expect(redBounds!.x).toBeLessThan(titleBounds!.x);
  expect(redBounds!.y+redBounds!.height).toBeLessThan(titleBounds!.y);
  expect(orangeBounds!.y+orangeBounds!.height).toBeLessThan(titleBounds!.y);
  await red.focus();
  await expect(red).toBeFocused();
  await page.evaluate(() => Promise.all(document.getAnimations().map(a=>a.finished.catch(()=>undefined))));
  expect((await new AxeBuilder({page}).include('[data-testid="platform-overview-card"]').withTags(["wcag2a","wcag2aa","wcag21aa"]).analyze()).violations).toEqual([]);
  await page.screenshot({path:`test-results/overview-anomalies-${test.info().project.name}.png`,fullPage:true});
});

test("overview counters follow the selected platform and period", async ({ page }) => {
  for (const [query,red,orange] of [["telegram&period=1d","4","2"],["vk&period=7d","8","12"],["all&period=7d","8","12"]]) {
    await page.goto(`/review?platform=${query}`);
    const card = page.getByTestId("platform-overview-card").first();
    await expect(card.getByTestId("overview-anomaly-level-3")).toHaveText(red);
    await expect(card.getByTestId("overview-anomaly-level-2")).toHaveText(orange);
  }
});

test("anomaly sort is the default and switching direction reverses the cards", async ({ page }) => {
  await page.goto("/review?platform=vk&period=7d");
  await expect(page.getByRole("combobox", {name:"Сортировка",exact:true})).toHaveValue("anomalies");
  await expect(page.getByRole("radio", {name:"По убыванию",exact:true})).toBeChecked();
  const cards = page.getByTestId("platform-overview-card");
  await expect(cards.first()).toContainText("Альфа Университет");
  await page.getByRole("radio", {name:"По возрастанию",exact:true}).check();
  await expect(cards.first()).toContainText("Бета Институт");
  await expect(page).toHaveURL(/direction=asc/);
});

test("large monthly metrics stay inside narrow columns and retain their exact values", async ({ page }, testInfo) => {
  await page.setViewportSize({width:testInfo.project.name === "mobile" ? 320 : 1208,height:900});
  await page.goto("/review?platform=vk&period=30d");
  const card = page.getByTestId("platform-overview-card").first();
  const totals = card.getByRole("region", {name:"Прирост за месяц",exact:true});
  await expect(totals.locator("b").nth(1)).toHaveText("12,3 млн");
  await expect(totals.locator("b").nth(1)).toHaveAttribute("title", "12\u00a0345\u00a0678");
  const overflow = await card.locator("section b").evaluateAll(elements => elements.some(element => {
    const bounds = element.getBoundingClientRect(), cell = element.parentElement!.getBoundingClientRect();
    return bounds.right > cell.right + 1;
  }));
  expect(overflow).toBe(false);
  await expect(totals.locator("[title*=\"против предыдущего периода\"]")).toHaveCount(0);
});
