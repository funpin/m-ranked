import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

for (const platform of ["telegram", "vk", "max", "rutube"]) {
  test(`${platform} navigation preserves platform in every destination`, async ({ page }) => {
    await page.goto(`/review?platform=${platform}`);
    await expect(page.getByTestId("brand")).toHaveAttribute("href", "/");
    await expect(page.locator('[data-testid="main-nav"] a[href^="/review"]')).toHaveAttribute("href", `/review?platform=${platform}`);
    for (const link of await page.getByTestId("main-nav").locator("a").all()) {
      const href = new URL((await link.getAttribute("href"))!, "http://test");
      // Методология одна на все площадки и параметра не несёт.
      expect(href.searchParams.get("platform")).toBe(href.pathname === "/methodology" ? null : platform);
    }
  });

  test(`${platform} comparison opens the all-institution dashboard on its platform`, async ({ page }) => {
    // Прежние ссылки (period в часах, выбор legacy id) открывают панель, а не 422.
    const legacy = platform === "telegram" ? "channels=2" : "institutions=2";
    const response = await page.goto(`/compare?platform=${platform}&period=24&submitted=true&${legacy}`);
    expect(response?.status()).toBe(200);
    await expect(page.getByTestId("compare-dashboard")).toBeVisible();
    await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
    await expect(page.getByTestId("platform-tabs").getByRole("tab", { selected: true })).toHaveAttribute("data-value", platform);
    if (platform !== "telegram") await expect(page.getByTestId("highlight-chip")).toContainText("Бета");
  });
}

test("comparison dashboard: platform tabs, highlight, ranking metric, table sort and period", async ({ page }) => {
  await page.goto("/compare");
  const dashboard = page.getByTestId("compare-dashboard");
  await expect(dashboard).toBeVisible();
  await expect(page.getByTestId("compare-kpi")).toHaveCount(6);
  // Все вузы без ограничения: 12 вузов фикстуры в рейтинге и в таблице.
  await expect(page.getByTestId("compare-table").locator("tbody tr")).toHaveCount(12);
  // На телефоне у вкладки короткая подпись «ВК», поэтому ищем по значению.
  await page.getByTestId("platform-tabs").locator('[role="tab"][data-value="vk"]').click();
  await expect(page).toHaveURL(/platform=vk/);
  await page.getByTestId("highlight-search").fill("Альфа");
  await page.getByRole("option").first().click();
  await expect(page.getByTestId("highlight-chip")).toContainText("Альфа");
  await expect(page).toHaveURL(/highlight=00000009-0000-4000-8000-000000000001/);
  await expect(page.getByTestId("compare-table").locator('tr[data-highlighted="true"]')).toHaveCount(1);
  await page.getByRole("combobox", { name: "Мера рейтинга" }).selectOption("engagement24");
  await expect(page.getByTestId("ranking-card")).toContainText("Вовлечённость за 24 часа");
  const table = page.getByTestId("compare-table");
  await table.getByRole("button", { name: /Публикаций/ }).click();
  await expect(table.getByRole("columnheader", { name: /Публикаций/ })).toHaveAttribute("aria-sort", "descending");
  await page.getByRole("tablist", { name: "Период" }).getByRole("tab", { name: "7 д", exact: true }).click();
  await expect(page).toHaveURL(/period=7d/);
  await expect(page).toHaveURL(/platform=vk/);
  await expect(page.getByTestId("highlight-chip")).toContainText("Альфа");
  await expect(page.locator('[data-testid="ranking-chart"] .recharts-bar-rectangle').first()).toBeVisible();
});

test("comparison charts and names stay inside their cards", async ({ page }) => {
  test.skip(page.viewportSize()!.width < 1024, "широкая компоновка");
  await page.goto("/compare");
  await expect(page.getByTestId("radar-chart")).toBeVisible();
  const layout = await page.evaluate(() => {
    const rect = (selector: string) => document.querySelector(selector)!.getBoundingClientRect();
    const card = rect('[data-testid="radar-card"]');
    const legend = rect('[data-testid="radar-card"] [aria-label="Выделенные вузы"]');
    const name = rect('[data-testid="compare-table"] tbody td:nth-child(2) button span:last-child');
    const next = rect('[data-testid="compare-table"] tbody td:nth-child(3)');
    return {
      legendInside: legend.bottom <= card.bottom && legend.left >= card.left && legend.right <= card.right,
      nameInside: name.right <= next.left,
      pageOverflow: document.documentElement.scrollWidth - innerWidth,
    };
  });
  expect(layout).toEqual({ legendInside: true, nameInside: true, pageOverflow: 0 });
  await page.getByRole("navigation", { name: "Разделы страницы" }).getByRole("link", { name: "Карта вузов" }).click();
  await expect.poll(() => page.evaluate(() => {
    const heading = document.querySelector('#map-title')!.getBoundingClientRect();
    const toolbar = document.querySelector('[data-testid="compare-dashboard"] > div')!.getBoundingClientRect();
    return heading.top >= toolbar.bottom;
  })).toBe(true);
});

test("form sort direction, platform autosubmit and browser history preserve fields", async ({ page }) => {
  await page.goto("/review?platform=vk&sort=subscribers&direction=desc");
  await page.locator('select[name="sort"]').selectOption("name");
  await expect(page.locator('input[name="direction"][value="asc"]')).toBeChecked();
  await page.getByTestId("platform-segments").locator('label:has(input[value="rutube"])').click();
  await expect(page).toHaveURL(/platform=rutube/);
  await expect(page.locator('select[name="sort"]')).toHaveValue("name");
  await expect(page.locator('input[name="direction"][value="asc"]')).toBeChecked();
  await page.goBack();
  await expect(page.locator('input[name="platform"][value="vk"]')).toBeChecked();
  await page.goForward();
  await expect(page.locator('input[name="platform"][value="rutube"]')).toBeChecked();
});

test("legacy validation returns 422 and repeated scalar chooses last", async ({ request, page }) => {
  expect((await request.get(`/?q=${"a".repeat(201)}`)).status()).toBe(422);
  for (const value of ["49", "bad", "3001"]) expect((await request.get(`/posts/1?history_limit=${value}`)).status()).toBe(422);
  await page.goto("/review?platform=telegram&platform=vk");
  await expect(page.locator('input[name="platform"][value="vk"]')).toBeChecked();
  await page.goto("/review?platform=invalid");
  await expect(page.locator('input[name="platform"][value="all"]')).toBeChecked();
});

test("findings list shows posts above norm with one badge and hidden-anomaly note", async ({ page }, info) => {
  await page.goto("/statistics?platform=vk");
  await expect(page.getByRole("heading", { level: 1, name: "Находки: посты выше нормы" })).toBeVisible();
  const rows = info.project.name === "mobile"
    ? page.getByTestId("findings-cards").locator("article")
    : page.getByTestId("findings-table").locator("tbody tr");
  await expect(rows).toHaveCount(20);
  await expect(rows.first()).toContainText("Вуз 001");
  await expect(rows.first()).toContainText("×5,0");
  // Один значок на строку: возраст важнее уровня анализа.
  await expect(rows.nth(1)).toContainText("предварительно, 6 ч");
  await expect(rows.nth(1)).not.toContainText("слабый сигнал");
  await expect(rows.nth(4)).toContainText("слабый сигнал");
  await expect(rows.nth(5)).toContainText("не проверен");
  await expect(rows.nth(6)).toContainText("по 12-му часу");
  await expect(rows.nth(6)).not.toContainText("предварительно");
  // Ноль — это значение, а не «нет данных».
  const zero = rows.nth(2);
  const mobile = info.project.name === "mobile";
  const zeroInteractions = mobile ? zero.locator("dd").nth(0) : zero.locator("td").nth(2);
  const zeroErv = mobile ? zero.locator("dd").nth(2) : zero.locator("td").nth(4);
  await expect(zeroInteractions).toHaveText("0");
  await expect(zeroErv).toHaveText("0,00%");
  await expect(zeroInteractions).not.toContainText("—");
  await expect(zeroErv).not.toContainText("—");
  // Неизвестный индекс — прочерк без «×».
  const unknownIndex = rows.nth(3).getByRole("button", { name: /^Индекс/ });
  await expect(unknownIndex).toHaveText("—");
  await expect(unknownIndex).not.toContainText("×");
  await expect(page.getByTestId("findings-hidden-note")).toContainText("3");
  await page.getByRole("button", { name: "Показать ещё" }).click();
  await expect(rows).toHaveCount(30);
});

test("findings restores URL state and searches", async ({ page }) => {
  await page.goto("/statistics?platform=vk&period=30d&sort=views24&direction=asc&q=alpha");
  await expect(page.locator('input[name="period"][value="30d"]')).toBeChecked();
  await expect(page.locator('select[name="sort"]')).toHaveValue("views24");
  await expect(page.locator('select[name="direction"]')).toHaveValue("asc");
  await expect(page.locator('input[name="q"]')).toHaveValue("alpha");
  await page.locator('input[name="q"]').fill("missing");
  await page.locator('input[name="q"]').press("Enter");
  await expect(page).toHaveURL(/q=missing/);
  await expect(page.getByText("Ничего не найдено")).toBeVisible();
  await page.goBack();
  await expect(page.locator('input[name="q"]')).toHaveValue("alpha");
});

test("findings groups by institution and links into institution mode", async ({ page }) => {
  await page.goto("/statistics?group=institution");
  const groups = page.getByTestId("findings-groups").locator("section");
  await expect(groups).toHaveCount(2);
  await expect(groups.first().getByRole("heading", { level: 2 })).toHaveText("Вуз 001");
  await groups.first().getByRole("link", { name: "Все посты вуза →" }).click();
  await expect(page).toHaveURL(/mode=institution/);
  await expect(page).toHaveURL(/institution=1/);
  await expect(page.getByRole("combobox", { name: "Вуз" })).toHaveValue("Вуз 001");
});

test("institution mode without a choice asks for one and unknown id is not an error", async ({ page }) => {
  await page.goto("/statistics?mode=institution");
  await expect(page.getByText("Выберите вуз, чтобы увидеть его посты")).toBeVisible();
  await page.getByRole("combobox", { name: "Вуз" }).fill("002");
  await page.getByRole("option", { name: /Вуз 002/ }).click();
  await expect(page).toHaveURL(/institution=2/);
  await page.goto("/statistics?mode=institution&institution=999");
  await expect(page.getByText("Вуз не найден — выберите другой")).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Вуз" })).toBeVisible();
  await expect(page.getByRole("alert").filter({ hasText: "Не удалось загрузить данные" })).toHaveCount(0);
  await expect(page.getByText("Не удалось загрузить данные")).toHaveCount(0);
  await expect(page.getByTestId("findings-table")).toHaveCount(0);
  await expect(page.getByTestId("findings-cards")).toHaveCount(0);
});

test("institution choice works when localStorage throws", async ({ page }) => {
  await page.addInitScript(() => {
    const fail = () => { throw new DOMException("denied", "SecurityError"); };
    Object.defineProperty(window, "localStorage", { configurable: true, get: fail });
  });
  await page.goto("/statistics?mode=institution");
  await expect(page.getByText("Выберите вуз, чтобы увидеть его посты")).toBeVisible();
  await page.getByRole("combobox", { name: "Вуз" }).fill("002");
  await page.getByRole("option", { name: /Вуз 002/ }).click();
  await expect(page).toHaveURL(/institution=2/);
  await expect(page.getByTestId(/findings-(table|cards)/).first()).toBeAttached();
  await expect(page.getByRole("alert").filter({ hasText: "Не удалось загрузить данные" })).toHaveCount(0);
});

test("findings filters popover applies publication types once on close", async ({ page }) => {
  await page.goto("/statistics");
  const trigger = page.getByRole("button", { name: /Фильтры/ });
  await trigger.click();
  await page.getByRole("checkbox", { name: "Видео" }).check();
  await expect(page).not.toHaveURL(/types=/);
  await page.keyboard.press("Escape");
  await expect(page).toHaveURL(/types=video/);
  await expect(page.getByRole("button", { name: /Фильтры · 1/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Фильтры/ })).toBeFocused();
});

test("mobile menu closes on Escape, navigation and desktop breakpoint", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/review?platform=vk");
  const header = page.getByTestId("header-inner");
  await expect(header).toBeVisible();
  const brand = header.getByTestId("brand");
  const toggle = header.getByTestId("menu-toggle");
  const actions = header.getByTestId("header-utility-actions");
  const [brandBox, toggleBox, actionsBox] = await Promise.all([brand.boundingBox(), toggle.boundingBox(), actions.boundingBox()]);
  expect(brandBox?.height).toBeLessThanOrEqual(32);
  expect((toggleBox?.x ?? 0) + (toggleBox?.width ?? 0)).toBeGreaterThan(360);
  expect((actionsBox?.x ?? 0) + (actionsBox?.width ?? 0)).toBeGreaterThan(360);
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

test("header follows the same horizontal grid as page content", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/review?platform=telegram");
  const headerInner = page.getByTestId("header-inner");
  const main = page.locator("#main-content");
  const brand = page.getByTestId("brand");
  const heading = page.getByRole("heading", { name: "Обзор каналов" });
  const [headerBox, mainBox, brandBox, headingBox, actionsBox, paddings] = await Promise.all([
    headerInner.boundingBox(),
    main.boundingBox(),
    brand.boundingBox(),
    heading.boundingBox(),
    headerInner.getByTestId("header-utility-actions").boundingBox(),
    Promise.all([headerInner, main].map((element) => element.evaluate((node) => {
      const style = getComputedStyle(node);
      return { left: style.paddingLeft, right: style.paddingRight };
    }))),
  ]);
  expect(headerBox?.x).toBe(mainBox?.x);
  expect(headerBox?.width).toBe(mainBox?.width);
  expect(paddings[0]).toEqual(paddings[1]);
  expect(brandBox?.x).toBe(headingBox?.x);
  expect((actionsBox?.x ?? 0) + (actionsBox?.width ?? 0)).toBe((mainBox?.x ?? 0) + (mainBox?.width ?? 0) - 40);
});

test("brand and favicon follow viewport and explicit theme", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("m-ranked-theme", "light"));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/review?platform=telegram");
  await expect(page.getByTestId("brand-logo-mark-light")).toBeVisible();
  await expect(page.getByTestId("brand-logo-wordmark")).toBeHidden();
  const favicon = page.locator('link[rel~="icon"][type="image/svg+xml"]');
  await expect(favicon).toHaveCount(1);
  await expect(favicon).toHaveAttribute("href", /logo-mark-light/);

  await page.getByRole("button", { name: /Переключить на тёмную/ }).click();
  await expect(page.getByTestId("brand-logo-mark-dark")).toBeVisible();
  await expect(favicon).toHaveAttribute("href", /logo-mark-dark/);

  await expect(page.locator('link[rel="icon"][type="image/png"][sizes="32x32"]')).toHaveAttribute("href", /\/icons\/favicon-32\.png\?v=20260921/);
  await expect(page.locator('link[rel="apple-touch-icon"][sizes="180x180"]')).toHaveAttribute("href", "/apple-touch-icon.png");
  await expect(page.locator('link[rel="apple-touch-icon-precomposed"][sizes="180x180"]')).toHaveAttribute("href", "/apple-touch-icon-precomposed.png");
  const startupImages = page.locator('link[rel="apple-touch-startup-image"]');
  await expect(startupImages).toHaveCount(24);
  await expect(page.locator('link[rel="apple-touch-startup-image"][media*="device-width: 393px"][media*="orientation: portrait"]'))
    .toHaveAttribute("href", "/splash/apple-splash-1179x2556.png");
  await expect(page.locator('link[rel="apple-touch-startup-image"][media*="device-width: 393px"][media*="orientation: landscape"]'))
    .toHaveAttribute("href", "/splash/apple-splash-2556x1179.png");
  await expect(page.locator('link[rel="manifest"]')).toHaveAttribute("href", "/manifest.webmanifest");

  await page.setViewportSize({ width: 1200, height: 800 });
  await expect(page.getByTestId("brand-logo-mark-dark")).toBeVisible();
  await expect(page.getByTestId("brand-logo-wordmark")).toBeVisible();
  await expect(page.getByTestId("brand-logo-wordmark")).toHaveText("m-ranked");
  await expect(page.getByTestId("brand-logo-wordmark")).toHaveCSS("white-space", "nowrap");
  await page.getByRole("button", { name: /Переключить на светлую/ }).click();
  await expect(page.getByTestId("brand-logo-mark-light")).toBeVisible();
  await expect(page.getByTestId("brand-logo-wordmark")).toBeVisible();
  await expect(favicon).toHaveAttribute("href", /logo-mark-light/);
});

test("web app manifest exposes current install icons", async ({ request }) => {
  const response = await request.get("/manifest.webmanifest");
  expect(response.ok()).toBeTruthy();
  const manifest = await response.json();
  expect(manifest.short_name).toBe("m-ranked");
  expect(manifest.id).toBe("/");
  expect(manifest.scope).toBe("/");
  expect(manifest.icons).toEqual(expect.arrayContaining([
    expect.objectContaining({ src: "/icons/app-icon-192.png?v=20260921", sizes: "192x192" }),
    expect.objectContaining({ src: "/icons/app-icon-512.png?v=20260921", sizes: "512x512" }),
  ]));
  for (const icon of ["/apple-touch-icon.png", "/apple-touch-icon-precomposed.png", "/icons/app-icon-192.png?v=20260921", "/icons/app-icon-512.png?v=20260921"]) {
    const image = await request.get(icon);
    expect(image.ok()).toBeTruthy();
    expect(image.headers()["content-type"]).toBe("image/png");
    expect((await image.body()).byteLength).toBeGreaterThan(400);
  }
  for (const [path, width, height] of [
    ["/splash/apple-splash-1179x2556.png", 1179, 2556],
    ["/splash/apple-splash-2556x1179.png", 2556, 1179],
  ] as const) {
    const image = await request.get(path);
    expect(image.ok()).toBeTruthy();
    expect(image.headers()["content-type"]).toBe("image/png");
    const body = await image.body();
    expect([body.readUInt32BE(16), body.readUInt32BE(20)]).toEqual([width, height]);
  }
});

test("PWA shell exposes iOS metadata and an opaque sticky header", async ({ page }) => {
  await page.goto("/review?platform=telegram");
  await expect(page.locator('meta[name="apple-mobile-web-app-capable"]')).toHaveAttribute("content", "yes");
  await expect(page.locator('meta[name="mobile-web-app-capable"]')).toHaveAttribute("content", "yes");
  await expect(page.locator('meta[name="apple-mobile-web-app-title"]')).toHaveAttribute("content", "m-ranked");
  await expect(page.locator('meta[name="apple-mobile-web-app-status-bar-style"]')).toHaveAttribute("content", "default");
  await expect(page.locator('meta[name="viewport"]')).toHaveAttribute("content", /viewport-fit=cover/);
  const header = page.getByRole("navigation", { name: "Основная навигация" });
  await expect(header).toHaveCSS("position", "sticky");
  expect(await header.evaluate((node) => {
    const probe = document.createElement("canvas").getContext("2d")!;
    probe.fillStyle = getComputedStyle(node).backgroundColor;
    probe.fillRect(0, 0, 1, 1);
    return probe.getImageData(0, 0, 1, 1).data[3];
  })).toBe(255);
});

test("retired export is absent from navigation and raw quality codes are absent from tables", async ({ page }) => {
  await page.goto("/accounts/00000001-0000-4000-8000-000000000001");
  await expect(page.getByTestId("main-nav").getByText("Экспорт CSV", { exact: true })).toHaveCount(0);
  await expect(page.locator('[title="exact" i]')).toHaveCount(0);
});

for (const theme of ["dark", "light"]) {
  test(`overview and interactive compare meet axe AA in ${theme} theme`, async ({ page }) => {
    for (const path of ["/review?platform=vk", "/compare?platform=vk"]) {
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
    await expect(page.getByTestId("archived-publication-text")).toHaveText("Сохранённый текст <script>без исполнения</script>");
    const chart=page.getByRole("img",{name:"Накопление показателей",exact:true});
    await expect(chart).toHaveAttribute("data-chart-ready","true");
    await chart.focus();await page.keyboard.press("End");
    await expect(page.getByRole("tooltip")).toContainText(["155"]);
    await page.keyboard.press("Escape");
    const auto=page.getByRole("button",{name:"Авто",exact:true}).first();await auto.click();await expect(auto).toHaveAttribute("aria-pressed","true");await page.reload();await expect(page.getByRole("button",{name:"Авто",exact:true}).first()).toHaveAttribute("aria-pressed","true");
    await page.getByTestId("snapshot-jump").last().click();await expect(page.locator("tr[data-selected]")).toHaveCount(1);
    if(path === "/posts/1") {await expect(page.locator("tbody tr")).toHaveCount(100);await page.getByRole("link",{name:"загрузить всю историю"}).click();await expect(page).toHaveURL(/history_limit=3000$/);await expect(page.locator("tbody tr")).toHaveCount(160);}
    expect((await new AxeBuilder({page}).withTags(["wcag2a","wcag2aa","wcag21aa"]).analyze()).violations).toEqual([]);
  });
}
test("account list and institutional zero/one/many routes preserve identity",async({page}) => {
  await page.goto("/channels/1");await expect(page.locator("tbody tr")).toHaveCount(2);
  await page.goto("/institutions/1?platform=telegram");await expect(page).toHaveURL(/\/accounts\/00000001-0000-4000-8000-000000000001$/);
  expect((await page.goto("/institutions/3?platform=telegram"))?.status()).toBe(404);
  await page.goto("/institutions/2?platform=telegram");await expect(page).toHaveURL(/\/accounts\/00000001-0000-4000-8000-000000000001$/);
  await page.goto("/platform-accounts/3");await expect(page.getByTestId("brand")).toHaveAttribute("href","/");await expect(page.locator('[data-testid="main-nav"] a[href^="/review"]')).toHaveAttribute("href","/review?platform=max");
});

test("overview and statistics share a dense responsive toolbar",async({page},info)=>{
  for(const path of ["/review?platform=telegram","/statistics?platform=telegram"]){
    await page.goto(path);
    const toolbar=page.getByTestId("filter-toolbar");
    await expect(toolbar).toBeVisible();
    const boxes=await toolbar.locator(":scope > :not(input[type=hidden]):not([role=status])").evaluateAll(elements=>elements.map(element=>{
      const box=element.getBoundingClientRect();return {top:Math.round(box.top),bottom:Math.round(box.bottom)};
    }));
    if(info.project.name==="desktop") expect(new Set(boxes.map(box=>box.top)).size).toBe(1);
    else {
      expect(new Set(boxes.map(box=>box.top)).size).toBeGreaterThan(1);
      expect(await page.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth)).toBe(0);
    }
  }
});
