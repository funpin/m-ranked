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
  await page.getByTestId("platform-segments").locator('label:has(input[value="rutube"])').click();
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

test("statistics all-platform mode has four independent publication slices", async ({ page, request }) => {
  expect((await request.get("/rating")).status()).toBe(404);
  await page.goto("/statistics?platform=all");
  await expect(page.getByRole("heading", { level: 1, name: "Статистика публикаций" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Вузы" })).toHaveCount(0);
  await expect(page.getByRole("heading", { level: 2 })).toHaveText(["Telegram", "ВКонтакте", "MAX", "Rutube"]);
  const tables = page.getByTestId("statistics-publications-table");
  await expect(tables).toHaveCount(4);
  await expect(tables.nth(0).locator("tbody tr")).toHaveCount(10);
  await expect(tables.nth(1).locator("tbody tr")).toHaveCount(10);
  await page.getByRole("button", { name: /Показать ещё/ }).first().click();
  await expect(tables.nth(0).locator("tbody tr")).toHaveCount(50);
  await expect(tables.nth(1).locator("tbody tr")).toHaveCount(10);
});

test("statistics concrete platform restores URL state, tabs, search and sorting", async ({ page }, info) => {
  await page.goto("/statistics?platform=vk&q=alpha&publication_sort=views&publication_direction=asc");
  await page.getByRole("button",{name:"Как считается: Как считается статистика"}).click();
  const statisticsNote=page.getByText(/Период — по дате публикации/);
  await expect(statisticsNote).toContainText("ERV = взаимодействия ÷ просмотры × 100%");
  await expect(statisticsNote).not.toContainText("последние накопленные счётчики");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("tab", { name: "Публикации" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("tab", { name: "Вузы" })).toBeVisible();
  await expect(page.locator('input[name="q"]')).toHaveValue("alpha");
  await expect(page.getByTestId("statistics-results-panel")).toHaveCount(1);
  await expect(page.getByTestId("statistics-results-panel")).toHaveClass(/md:bg-card/);
  const publicationTarget=info.project.name==="mobile"
    ? page.getByTestId("statistics-publication-cards").locator("article").first()
    : page.getByTestId("statistics-publications-table").locator("tbody tr").first();
  await expect(publicationTarget.getByText("Вуз 001",{exact:true})).toBeVisible();
  await expect(publicationTarget.getByText("№1",{exact:true})).toBeVisible();
  await expect(publicationTarget.getByText("Полное название университета 001",{exact:true})).toBeVisible();
  await expect(publicationTarget).not.toContainText("Аккаунт 1");
  if (info.project.name === "mobile") {
    await expect(page.locator('select[name="publication_direction"]')).toHaveValue("asc");
  } else {
    await expect(page.getByRole("columnheader", { name: /Просмотры/ })).toHaveAttribute("aria-sort", "ascending");
  }
  await page.locator('input[name="q"]').fill("missing");
  await page.locator('input[name="q"]').press("Enter");
  await expect(page).toHaveURL(/q=missing/);
  await expect(page.getByText("Ничего не найдено")).toBeVisible();
  await page.goBack();
  await expect(page.locator('input[name="q"]')).toHaveValue("alpha");
  await page.getByRole("tab", { name: "Вузы" }).click();
  await expect(page).toHaveURL(/view=entities/);
  await expect(page.getByTestId("statistics-entities-table").locator("tbody tr")).toHaveCount(20);
  const entityTarget=info.project.name==="mobile"
    ? page.getByTestId("statistics-entity-cards").locator("article").first()
    : page.getByTestId("statistics-entities-table").locator("tbody tr").first();
  await expect(entityTarget.getByText("Вуз 001",{exact:true})).toBeVisible();
  await expect(entityTarget.getByText("Полное название университета 001",{exact:true})).toBeVisible();
  await expect(entityTarget).not.toContainText(/выборка|для ERV/i);
  await entityTarget.getByRole("button",{name:/ERV .*Подробнее о расчёте/}).first().hover();
  await expect(page.locator('[data-slot="tooltip-content"][data-open]')).toContainText("ERV по сумме");
  await expect(page.locator('[data-slot="tooltip-content"][data-open]')).toContainText("20 из 20");
  await page.keyboard.press("Escape");
  if(info.project.name==="desktop"){
    await page.getByRole("button",{name:"Как считается ERV вузов"}).hover();
    await expect(page.locator('[data-slot="tooltip-content"][data-open]')).toContainText("сумма взаимодействий");
    await expect(page.locator('[data-slot="tooltip-content"][data-open]')).toContainText("20 последних публикаций");
    await page.keyboard.press("Escape");
  }
  const medianHelp = info.project.name === "mobile"
    ? entityTarget.getByRole("button",{name:"Что означает медиана взаимодействий"})
    : page.getByRole("button",{name:"Что означает медиана взаимодействий"});
  await medianHelp.first().hover();
  await expect(page.locator('[data-slot="tooltip-content"][data-open]')).toContainText("у половины публикаций");
  await expect(page.locator('[data-slot="tooltip-content"][data-open]')).toContainText("20 последних публикаций");
  await page.keyboard.press("Escape");
  await entityTarget.getByRole("link").first().click();
  await expect(page).toHaveURL(/\/accounts\/00000002-0000-4000-8000-000000000001$/);
});

test("statistics mobile uses cards and keeps zero distinct from unknown", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/statistics?platform=telegram");
  await expect(page.getByTestId("statistics-publication-cards").locator("article")).toHaveCount(20);
  await expect(page.getByTestId("statistics-publications-table")).toBeHidden();
  const cards = page.getByTestId("statistics-publication-cards");
  await expect(cards.getByText("—").first()).toBeVisible();
  await expect(cards.getByText("1,00%").first()).toBeVisible();
});

test("mobile menu closes on Escape, navigation and desktop breakpoint", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/?platform=vk");
  const brand = page.getByTestId("brand");
  const toggle = page.getByTestId("menu-toggle");
  const actions = page.getByTestId("header-utility-actions");
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
  await page.goto("/?platform=telegram");
  const headerInner = page.getByTestId("header-inner");
  const main = page.locator("#main-content");
  const brand = page.getByTestId("brand");
  const heading = page.getByRole("heading", { name: "Обзор каналов" });
  const [headerBox, mainBox, brandBox, headingBox, actionsBox, paddings] = await Promise.all([
    headerInner.boundingBox(),
    main.boundingBox(),
    brand.boundingBox(),
    heading.boundingBox(),
    page.getByTestId("header-utility-actions").boundingBox(),
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
  await page.goto("/?platform=telegram");
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
});

test("PWA shell exposes iOS metadata and a frosted sticky header", async ({ page }) => {
  await page.goto("/?platform=telegram");
  await expect(page.locator('meta[name="apple-mobile-web-app-capable"]')).toHaveAttribute("content", "yes");
  await expect(page.locator('meta[name="mobile-web-app-capable"]')).toHaveAttribute("content", "yes");
  await expect(page.locator('meta[name="apple-mobile-web-app-title"]')).toHaveAttribute("content", "m-ranked");
  await expect(page.locator('meta[name="viewport"]')).toHaveAttribute("content", /viewport-fit=cover/);
  const header = page.getByRole("navigation", { name: "Основная навигация" });
  await expect(header).toHaveCSS("position", "sticky");
  expect(await header.evaluate((node) => {
    const style = getComputedStyle(node);
    return style.backdropFilter || style.getPropertyValue("-webkit-backdrop-filter");
  })).toContain("blur");
});

test("retired export is absent from navigation and raw quality codes are absent from tables", async ({ page }) => {
  await page.goto("/accounts/00000001-0000-4000-8000-000000000001");
  await expect(page.getByTestId("main-nav").getByText("Экспорт CSV", { exact: true })).toHaveCount(0);
  await expect(page.locator('[title="exact" i]')).toHaveCount(0);
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
  await page.goto("/platform-accounts/3");await expect(page.getByTestId("brand")).toHaveAttribute("href","/?platform=max");
});

test("overview and statistics share one-row desktop and wrapped mobile filters",async({page},info)=>{
  for(const path of ["/?platform=telegram","/statistics?platform=telegram"]){
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
