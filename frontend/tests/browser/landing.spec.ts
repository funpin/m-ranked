import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test("главная показывает сводку и площадки из данных, и каждая страница — одной ссылкой", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Соцсети вузов.");
  const stats = page.getByTestId("landing-stats");
  // Числа ниже экрана досчитывают, когда до них долистали.
  await stats.scrollIntoViewIfNeeded();
  await expect(stats).toContainText("Под наблюдением");
  await expect(stats).toContainText("98 765");
  await expect(page.getByTestId("landing-platforms").locator(":scope > li")).toHaveCount(4);
  const vk = page.getByTestId("landing-platforms").locator(":scope > li").first();
  await expect(vk).toContainText("ВКонтакте");
  await expect(vk).toContainText("12");
  await expect(vk).toContainText("сообществ");

  // Шапка не в счёт: в содержимом главной каждая страница — одной ссылкой.
  const main = page.locator("#main-content");
  await expect(main.locator('a[href="/review"]')).toHaveCount(1);
  await expect(main.locator('a[href="/compare"]')).toHaveCount(1);
  await expect(main.locator('a[href="/methodology"]')).toHaveCount(1);
  await expect(main.locator('a[href="/methodology/api"]')).toHaveCount(1);
  await expect(main.locator('a[href="https://github.com/funpin/m-ranked"]')).toHaveCount(1);
});

test("главная ведёт в обзор, а якорь и ссылка API остаются доступными под шапкой", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await page.getByRole("link", { name: "Как это устроено" }).click();
  await expect(page).toHaveURL(/#how$/);
  const heading = page.locator("#how");
  const header = page.getByRole("navigation", { name: "Основная навигация" });
  await expect(heading).toBeInViewport();
  expect((await heading.boundingBox())!.y).toBeGreaterThan((await header.boundingBox())!.height);
  await expect(page.locator('#main-content a[href="/methodology/api"]')).toHaveCount(1);
  await expect(page.getByTestId("verify-api")).toContainText("/api/v1/site/summary");
  await page.getByTestId("landing-cta").click();
  await expect(page).toHaveURL(/\/review(?:\?|$)/);
});

test("графики главной загружаются, только когда до них долистали", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("landing-reach")).toBeAttached();
  await expect(page.getByTestId("reach-chart")).toHaveCount(0);
  await page.getByTestId("landing-reach").scrollIntoViewIfNeeded();
  await expect(page.getByTestId("reach-chart")).toBeVisible();
  const rhythm = page.getByTestId("landing-rhythm");
  await rhythm.scrollIntoViewIfNeeded();
  await expect(page.getByTestId("hourly-chart")).toBeVisible();
  await rhythm.getByRole("radio", { name: "ВКонтакте" }).click();
  await expect(rhythm.getByRole("radio", { name: "ВКонтакте" })).toHaveAttribute("aria-checked", "true");
  // Остальные графики — в ленте: листаются стрелкой, грузятся, когда видны.
  await rhythm.getByRole("button", { name: "Ритм площадок: дальше" }).click();
  await rhythm.getByText("Дни недели.").scrollIntoViewIfNeeded();
  await expect(page.getByTestId("timing-heatmap")).toBeVisible();
  await rhythm.getByText("Итоги анализа.").scrollIntoViewIfNeeded();
  await expect(page.getByTestId("levels-by-platform")).toBeVisible();
  await expect(rhythm.getByRole("button", { name: "Ритм площадок: назад" })).toBeEnabled();
});

test("коридор нормы переключает форму роста по выбору читателя", async ({ page }) => {
  await page.goto("/");
  const corridor = page.getByTestId("norm-corridor");
  await corridor.scrollIntoViewIfNeeded();
  await corridor.getByRole("radio", { name: "Поздний скачок" }).click();
  await expect(corridor.getByRole("radio", { name: "Поздний скачок" })).toHaveAttribute("aria-checked", "true");
  await expect(corridor).toContainText("вдруг — резкий прирост");
  await expect(corridor).toContainText("обычный разброс площадки");
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
      await expect(page.getByTestId("landing-rhythm")).toHaveCount(1);
      await page.getByTestId("landing-rhythm").scrollIntoViewIfNeeded();
      await expect(page.getByTestId("hourly-chart")).toBeVisible();
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

test("в шапке — авторы проекта рядом с GitHub", async ({ page }) => {
  test.skip(page.viewportSize()!.width <= 780, "на узком экране авторы скрыты");
  await page.goto("/");
  const contributors = page.getByTestId("contributors");
  await expect(contributors.getByRole("link")).not.toHaveCount(0);
  await expect(contributors.getByRole("link").first()).toHaveAttribute("href", /^https:\/\/github\.com\//);
});

test("телефон показывает сравнение площадок, а появления проигрываются один раз", async ({ page }) => {
  await page.goto("/");
  const phone = page.getByTestId("phone-showcase");
  await expect(phone.getByRole("img", { name: /Сравнение площадок за 30 дней/ })).toBeAttached();
  await expect(phone.locator(".landing-phone-tracks li")).toHaveCount(4);
  // Заголовок раздела проявился — и остаётся проявленным после прокрутки назад и снова вниз.
  const heading = page.locator("#landing-rhythm");
  await heading.scrollIntoViewIfNeeded();
  await expect(heading).toHaveClass(/is-in/);
  await page.evaluate(() => window.scrollTo(0, 0));
  await heading.scrollIntoViewIfNeeded();
  await expect(heading).toHaveClass(/is-in/);
  await expect(heading).toHaveCSS("opacity", "1");
});
