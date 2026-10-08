import { expect, test } from "@playwright/test";

const ALPHA = "00000009-0000-4000-8000-000000000001";

test("comparison search: words in any order, keyboard choice, empty state, chips survive a tab change", async ({ page }) => {
  await page.goto("/compare");
  const main = page.getByRole("main");
  await main.getByTestId("highlight-search").click();
  const search = main.getByRole("combobox", { name: "Найти вуз для выделения" });
  await expect(search).toBeFocused();
  await page.keyboard.type("университет альфа");
  await expect(page.getByRole("option").first()).toContainText("Альфа");
  await page.keyboard.press("Enter");
  await expect(main.getByTestId("highlight-chip")).toHaveCount(1);
  await expect(page).toHaveURL(new RegExp(`highlight=${ALPHA}`));

  await search.fill("несуществующий вуз");
  await expect(page.getByText("Ничего не найдено")).toBeVisible();
  await page.keyboard.press("Escape");

  await main.getByTestId("platform-tabs").locator('[role="tab"][data-value="rutube"]').click();
  await expect(main.getByTestId("highlight-chip")).toContainText("Альфа");
});

test("comparison profile asks for a university instead of picking one", async ({ page }) => {
  await page.goto("/compare");
  const main = page.getByRole("main");
  const radar = main.getByTestId("radar-card");
  await expect(radar.getByTestId("radar-empty")).toBeVisible();
  await radar.getByRole("button", { name: "Выбрать вуз" }).click();
  await expect(main.getByRole("combobox", { name: "Найти вуз для выделения" })).toBeFocused();
});

test("comparison timing follows highlighted universities and curves pick on click", async ({ page }) => {
  test.skip(page.viewportSize()!.width < 1024, "широкая компоновка");
  // Браузер догружает вуз с того же адреса; в проде /api раздаёт nginx, здесь —
  // фикстура API.
  await page.route("**/api/v1/compare/institutions/**", async (route) => {
    const target = new URL(route.request().url());
    target.host = "127.0.0.1:18091";
    await route.fulfill({ response: await route.fetch({ url: target.toString() }) });
  });
  await page.goto(`/compare?platform=telegram&highlight=${ALPHA}`);
  const main = page.getByRole("main");
  // Без явной прокрутки: потоковая отрисовка заменяет разметку панели, и
  // прокрутка к ещё не заменённому узлу падала на «not attached».
  const hourly = main.getByTestId("hourly-card");
  await expect(hourly.locator(".recharts-line")).toHaveCount(2);
  await expect(hourly.getByText("Час выхода, московское время")).toBeVisible();
  await expect(main.getByTestId("types-chart-count")).toContainText("Доля публикаций, %");

  const heatmap = main.getByTestId("heatmap-card");
  await heatmap.getByRole("combobox", { name: "Чьи публикации показать" }).selectOption(ALPHA);
  await expect(heatmap).toContainText("Альфа");
  const cell = heatmap.getByRole("gridcell").nth(30);
  await cell.focus();
  await page.keyboard.press("ArrowRight");
  await expect(heatmap.getByTestId("heatmap-readout")).toContainText("публ.");

  const curves = main.getByTestId("curves-card");
  const before = await main.getByTestId("highlight-chip").count();
  await curves.locator("[data-testid=curves-backdrop] g[data-institution]").first().dispatchEvent("click");
  await expect(main.getByTestId("highlight-chip")).toHaveCount(before + 1);
  await expect(curves.getByText("Время после выхода поста")).toBeVisible();
});

test("comparison ranking, map and presence pick a university on click", async ({ page }) => {
  test.skip(page.viewportSize()!.width < 1024, "широкая компоновка");
  await page.goto("/compare");
  const main = page.getByRole("main");
  const chips = main.getByTestId("highlight-chip");
  await expect(chips).toHaveCount(0);
  await main.getByTestId("ranking-chart").locator(".recharts-bar-rectangle").nth(1).click();
  await expect(chips).toHaveCount(1);
  await main.getByTestId("scatter-chart").locator(".recharts-scatter-symbol").first().click();
  await expect(chips).toHaveCount(2);
  // Название у строки рейтинга — в одну строку и тоже выбирает вуз.
  const name = main.getByTestId("ranking-chart").locator(".recharts-yAxis-tick-labels text").nth(3);
  await expect(name.locator("tspan")).toHaveCount(0);
  // Проверяется обработчик подписи, а не попадание мышью в 11-пиксельный текст:
  // под нагрузкой CI клик по SVG-тексту изредка промахивался.
  await name.dispatchEvent("click");
  await expect(chips).toHaveCount(3);
  // Уровни анализа сами переходят к последнему выделенному вузу.
  const levels = main.getByTestId("levels-card");
  await expect(levels.getByRole("combobox", { name: "Чьи посты показать" })).not.toHaveValue("all");
  await levels.getByRole("combobox", { name: "Чьи посты показать" }).selectOption("all");
  await expect(levels).not.toContainText(" · ");
});
