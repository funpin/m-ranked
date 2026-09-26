import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test("главная показывает сводку и площадки из данных, и каждая страница — одной ссылкой", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Соцсети вузов.");
  const stats = page.getByTestId("landing-stats");
  // Числа ниже экрана досчитывают, когда до них долистали.
  await stats.scrollIntoViewIfNeeded();
  await expect(stats).toContainText("вузов под наблюдением");
  await expect(stats).toContainText("98 765");
  await expect(page.getByTestId("landing-platforms").locator(":scope > li")).toHaveCount(4);
  await expect(page.getByTestId("landing-platforms")).toContainText("12 сообществ");

  // Шапка не в счёт: в содержимом главной каждая страница — одной ссылкой.
  const main = page.locator("#main-content");
  await expect(main.locator('a[href="/rating"]')).toHaveCount(1);
  await expect(main.locator('a[href="/compare"]')).toHaveCount(1);
  await expect(main.locator('a[href="/methodology"]')).toHaveCount(1);
  await expect(main.locator('a[href="/methodology/api"]')).toHaveCount(1);
  await expect(main.locator('a[href="https://github.com/funpin/m-ranked"]')).toHaveCount(1);
});

test("графики главной загружаются, только когда до них долистали", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("landing-reach")).toBeAttached();
  await expect(page.getByTestId("reach-chart")).toHaveCount(0);
  await page.getByTestId("landing-reach").scrollIntoViewIfNeeded();
  await expect(page.getByTestId("reach-chart")).toBeVisible();
  await page.getByTestId("landing-curves").scrollIntoViewIfNeeded();
  await expect(page.getByTestId("curves-chart")).toBeVisible();
  await page.getByTestId("landing-curves").getByRole("radio", { name: "ВКонтакте" }).click();
  await expect(page.getByTestId("landing-curves").getByRole("radio", { name: "ВКонтакте" })).toHaveAttribute("aria-checked", "true");
});

test("коридор нормы переключает форму роста по выбору читателя", async ({ page }) => {
  await page.goto("/");
  const corridor = page.getByTestId("norm-corridor");
  await corridor.scrollIntoViewIfNeeded();
  await corridor.getByRole("radio", { name: "Поздний скачок" }).click();
  await expect(corridor.getByRole("radio", { name: "Поздний скачок" })).toHaveAttribute("aria-checked", "true");
  await expect(corridor).toContainText("вдруг — резкий прирост");
  await expect(corridor.getByRole("img")).toHaveAttribute("aria-label", /поздний скачок/);
});

for (const theme of ["light", "dark"]) {
  test(`главная укладывается в ширину и проходит axe AA в ${theme} теме`, async ({ page }) => {
    await page.addInitScript((value) => localStorage.setItem("m-ranked-theme", value), theme);
    // Без движения блоки видны сразу: контраст меряется по итоговому виду.
    await page.emulateMedia({ reducedMotion: "reduce" });
    for (const width of [390, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/");
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await page.getByTestId("landing-curves").scrollIntoViewIfNeeded();
      await expect(page.getByTestId("curves-chart")).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBe(0);
      expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
    }
  });
}

test("первый экран без цифр: сводка ниже сгиба, а трёхмерная модель догружается отдельно", async ({ page }) => {
  await page.goto("/");
  const stats = page.getByTestId("landing-stats");
  const top = await stats.evaluate((node) => node.getBoundingClientRect().top);
  expect(top).toBeGreaterThanOrEqual(await page.evaluate(() => window.innerHeight));
  const scene = page.getByTestId("hero-scene");
  await expect(scene).toBeAttached();
  const webgl = await page.evaluate(() => Boolean(document.createElement("canvas").getContext("webgl2")));
  if (webgl) await expect(scene).toHaveAttribute("data-ready", "true", { timeout: 15_000 });
});
