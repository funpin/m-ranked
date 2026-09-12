import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

for (const platform of ["telegram", "vk", "max", "rutube"]) {
  test(`${platform} navigation preserves platform in every destination`, async ({ page }) => {
    await page.goto(`/?platform=${platform}`);
    await expect(page.getByTestId("brand")).toHaveAttribute("href", `/?platform=${platform}`);
    for (const link of await page.getByTestId("main-nav").locator("a").all()) {
      expect(new URL((await link.getAttribute("href"))!, "http://test").searchParams.get("platform")).toBe(platform);
    }
  });

  test(`${platform} default / explicit / empty comparison`, async ({ page }) => {
    await page.goto(`/compare?platform=${platform}&period=24`);
    await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
    if (platform === "max") { await expect(page.getByRole("heading", { name: "Сравнение · MAX", exact: true })).toBeVisible(); return; }
    await expect(page.getByRole("checkbox", { name: /Альфа/ })).toBeChecked();
    await expect(page.getByRole("checkbox", { name: /Бета/ })).toBeChecked();
    const parameter = platform === "telegram" ? "channels" : "institutions";
    await page.goto(`/compare?platform=${platform}&period=24&submitted=true&${parameter}=2`);
    await expect(page.getByRole("checkbox", { name: /Бета/ })).toBeChecked();
    await page.goto(`/compare?platform=${platform}&submitted=true`);
    await expect(page.getByText(/Выберите хотя бы один/)).toBeVisible();
    const rejected = await page.goto(`/compare?platform=${platform}&submitted=true&${parameter}=invalid`);
    expect(rejected?.status()).toBe(422);
  });
}

test("compare search, bulk controls, count, legend and focused point tooltip work", async ({ page }) => {
  await page.goto("/compare?platform=vk&period=24");
  await page.getByRole("button", { name: "Снять выбор" }).click();
  await expect(page.getByText("Выбрано: 0 из 2")).toBeVisible();
  await page.getByRole("searchbox").fill("Альфа");
  await expect(page.getByRole("checkbox", { name: /Бета/ })).toBeHidden();
  await page.getByRole("button", { name: "Выбрать все" }).click();
  await expect(page.getByText("Выбрано: 2 из 2")).toBeVisible();
  const legend = page.getByRole("button", { name: "Скрыть линию: Альфа Университет" }).first();
  await legend.focus(); await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "Вернуть линию: Альфа Университет" })).toHaveCount(1);
  const point = page.getByTestId("comparison-chart").first();
  await expect(point).toHaveAttribute("data-chart-ready", "true");
  await point.focus();
  await expect(page.getByRole("tooltip")).toContainText(["Выборка: 2"]);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("tooltip")).toHaveCount(0);
});

test("form sort direction, platform autosubmit and browser history preserve fields", async ({ page }) => {
  await page.goto("/?platform=vk&sort=subscribers&direction=desc");
  await page.locator('select[name="sort"]').selectOption("name");
  await expect(page.locator('select[name="direction"]')).toHaveValue("asc");
  await page.locator('.segments label:has(input[value="rutube"])').click();
  await expect(page).toHaveURL(/platform=rutube/);
  await expect(page.locator('select[name="sort"]')).toHaveValue("name");
  await expect(page.locator('select[name="direction"]')).toHaveValue("asc");
  await page.goBack();
  await expect(page.locator('input[name="platform"][value="vk"]')).toBeChecked();
  await page.goForward();
  await expect(page.locator('input[name="platform"][value="rutube"]')).toBeChecked();
});

test("legacy validation returns 422 and repeated scalar chooses last", async ({ request, page }) => {
  expect((await request.get(`/?q=${"a".repeat(201)}`)).status()).toBe(422);
  for (const value of ["49", "bad", "3001"]) expect((await request.get(`/posts/1?history_limit=${value}`)).status()).toBe(422);
  await page.goto("/?platform=telegram&platform=vk");
  await expect(page.locator('input[name="platform"][value="vk"]')).toBeChecked();
  await page.goto("/?platform=invalid");
  await expect(page.locator('input[name="platform"][value="telegram"]')).toBeChecked();
});

for (const platform of ["telegram", "vk", "rutube"]) {
  test(`${platform} rating exposes all 205 rows with stable global ranks`, async ({ page }) => {
    await page.goto(`/rating?platform=${platform}`);
    const first = await page.locator("tbody tr .entity-cell > a:first-child").allTextContents();
    expect(first).toHaveLength(200);
    await page.getByRole("link", { name: "Следующая страница рейтинга" }).click();
    await expect(page).toHaveURL(/entityCursor=/);
    const next = await page.locator("tbody tr .entity-cell > a:first-child").allTextContents();
    expect(next).toHaveLength(5);
    expect(new Set([...first, ...next]).size).toBe(205);
    await expect(page.locator(".rank-cell").first()).toHaveText("201");
    await expect(page.getByRole("link", { name: "Следующая страница рейтинга" })).toHaveCount(0);
  });
}

test("mobile menu closes on Escape, navigation and desktop breakpoint", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/?platform=vk");
  const toggle = page.getByTestId("menu-toggle");
  await toggle.click();
  await page.keyboard.press("Escape");
  await expect(toggle).toBeFocused();
  await toggle.click();
  await page.getByRole("link", { name: "Сравнение", exact: true }).click();
  await expect(page).toHaveURL(/compare\?platform=vk/);
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await toggle.click();
  await page.setViewportSize({ width: 1440, height: 900 });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
});

for (const theme of ["dark", "light"]) {
  test(`overview and interactive compare meet axe AA in ${theme} theme`, async ({ page }) => {
    for (const path of ["/?platform=vk", "/compare?platform=vk&period=24"]) {
      await page.goto(path);
      // Colour transitions are still running right after the attribute flips,
      // and sampling mid-transition reports blended values that exist in
      // neither theme. Let them settle before measuring the settled page.
      await page.evaluate(async (value) => {
        document.documentElement.dataset.theme = value;
        await Promise.allSettled(document.getAnimations().map((animation) => animation.finished));
      }, theme);
      const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
      expect(result.violations).toEqual([]);
    }
  });
}

for(const path of ["/posts/1","/platform-posts/1"]) {
  test(`${path} real history controls, archive, reactions and keyboard`,async({page}) => {
    await page.goto(path);
    await expect(page.getByRole("heading",{name:"Сохранённый текст публикации"})).toBeVisible();
    await expect(page.locator(".archived-publication-text")).toHaveText("Сохранённый текст <script>без исполнения</script>");
    await expect(page.locator("canvas").first()).toHaveAttribute("data-chart-ready","true");
    await page.locator("canvas").first().focus();await page.keyboard.press("End");
    await expect(page.getByRole("tooltip")).toContainText(["155"]);
    await page.keyboard.press("Escape");
    const auto=page.getByRole("button",{name:"Авто",exact:true}).first();await auto.click();await expect(auto).toHaveAttribute("aria-pressed","true");await page.reload();await expect(page.getByRole("button",{name:"Авто",exact:true}).first()).toHaveAttribute("aria-pressed","true");
    await page.locator(".snapshot-jump").last().click();await expect(page.locator(".snapshot-highlight")).toHaveCount(1);
    if(path === "/posts/1") {await expect(page.locator("tbody tr")).toHaveCount(100);await page.getByRole("link",{name:"загрузить всю историю"}).click();await expect(page).toHaveURL(/history_limit=3000$/);await expect(page.locator("tbody tr")).toHaveCount(160);}
    expect((await new AxeBuilder({page}).withTags(["wcag2a","wcag2aa","wcag21aa"]).analyze()).violations).toEqual([]);
  });
}
test("account list and institutional zero/one/many routes preserve identity",async({page}) => {
  await page.goto("/channels/1");await expect(page.locator("tbody tr")).toHaveCount(2);
  await page.goto("/institutions/1?platform=telegram");await expect(page).toHaveURL(/\/accounts\/00000001-0000-4000-8000-000000000001$/);
  await page.goto("/institutions/3?platform=telegram");await expect(page.getByText("Telegram-каналы вуза не добавлены.")).toBeVisible();
  await page.goto("/institutions/2?platform=telegram");await expect(page.locator(".platform-overview-card")).toHaveCount(2);
  await page.goto("/platform-accounts/3");await expect(page.getByTestId("brand")).toHaveAttribute("href","/?platform=max");
});
