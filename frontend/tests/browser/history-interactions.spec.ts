import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("publication charts use the full content width and stack vertically",async({page})=>{
  await page.setViewportSize({width:1440,height:900});
  await page.goto("/posts/1");
  const stack=page.getByTestId("publication-chart-stack");
  const total=page.getByRole("img",{name:"Накопление показателей",exact:true});
  const growth=page.getByRole("img",{name:"Прирост между сохранёнными точками",exact:true});
  await expect(total).toHaveAttribute("data-chart-ready","true");
  const [stackBox,totalBox,growthBox]=await Promise.all([stack.boundingBox(),total.boundingBox(),growth.boundingBox()]);
  expect(stackBox).not.toBeNull();expect(totalBox).not.toBeNull();expect(growthBox).not.toBeNull();
  expect(totalBox!.width).toBeGreaterThan(stackBox!.width*0.9);
  expect(growthBox!.width).toBeCloseTo(totalBox!.width,0);
  expect(growthBox!.y).toBeGreaterThan(totalBox!.y+totalBox!.height);
});

for(const [path,platform,platformLabel,reaction,hasComments,hasShares] of [
  ["/posts/1","telegram","TG","реакций",true,false], ["/platform-posts/21","vk","ВК","лайков",true,true],
  ["/platform-posts/1","max","MAX","реакций",true,false], ["/platform-posts/41","rutube","RUTUBE","лайков",false,false],
] as const) {
  test(`${path} uses shared metrics, ratios and exact growth tooltips`, async({page},testInfo) => {
    await page.goto(path);
    const meta=page.getByTestId("publication-meta");
    await expect(meta).toHaveAttribute("data-platform",platform);
    await expect(meta.locator(":scope > span").first()).toHaveText(platformLabel);
    await expect(page.getByTestId("publication-meta-copy")).toHaveText(/^Опубликовано: .* · история (полная|неполная) · тип: [^·]+$/);
    const total=page.getByRole("img",{name:"Накопление показателей",exact:true});
    const growth=page.getByRole("img",{name:"Прирост между сохранёнными точками",exact:true});
    await expect(total).toHaveAttribute("data-chart-ready","true");
    await expect(page.getByRole("button",{name:"Всего комментариев",exact:true})).toHaveCount(hasComments?1:0);
    await expect(page.getByRole("button",{name:"Всего репостов",exact:true})).toHaveCount(hasShares?1:0);
    await total.focus();await page.keyboard.press("End");
    await expect(page.getByRole("tooltip").first()).toContainText("(+6 д 15:00:00)");
    await expect(page.getByRole("tooltip").first()).toContainText(`${reaction==="лайков"?"Лайки":"Реакции"} / просмотры: 9.75%`);
    await growth.focus();await page.keyboard.press("End");
    await expect(page.getByRole("tooltip")).toContainText(`Прирост ${reaction}: -3`);
    await page.keyboard.press("Escape");
    const box=await growth.boundingBox();expect(box).not.toBeNull();
    // The pointer tooltip is rendered text now, so it is read rather than
    // intercepted on its way to a canvas.
    await growth.hover({position:{x:box!.width-20,y:box!.height/2}});
    await expect(growth.getByText(/\(\+(?:\d+ д )?\d+:\d{2}:\d{2}\)/)).toBeVisible();
    await expect(growth.getByText(/^Прирост (реакций|лайков): [+-]?\d/)).toBeVisible();
    await growth.screenshot({path:testInfo.outputPath("growth-tooltip.png")});
  });
}

test("chart activation selects the exact row and reveals an old collapsed point",async({page}) => {
  await page.goto("/posts/1");
  await page.getByRole("link",{name:"загрузить всю историю"}).click();
  await expect(page).toHaveURL(/history_limit=3000$/);
  const total=page.getByRole("img",{name:"Накопление показателей",exact:true});
  await expect(total).toHaveAttribute("data-chart-ready","true");
  await expect(page.locator("tbody tr")).toHaveCount(160);
  const box=await total.boundingBox();expect(box).not.toBeNull();
  // The left axis consumes roughly 72 px. Click just inside the plotting area:
  // x=60 lands on the axis on the mobile viewport and Recharts may reuse a
  // middle active label instead of selecting an old point.
  await total.click({position:{x:80,y:box!.height-65}});
  const selected=page.locator("tr[data-selected]");
  await expect(selected).toHaveCount(1);
  const id=await selected.getAttribute("id");
  expect(Number(id!.replace("snapshot-",""))).toBeLessThan(160);
  await expect(selected).toBeInViewport();
  await expect(selected.getByTestId("snapshot-jump")).toBeFocused();
  // Keyboard activation uses the same reveal-and-scroll path after collapsing.
  await page.getByRole("button",{name:"свернуть историю"}).click();
  await expect(page.locator("tbody tr")).toHaveCount(100);
  await total.focus();await page.keyboard.press("Home");await page.keyboard.press("Enter");
  await expect(page.locator("#snapshot-1")).toBeInViewport();
  await expect(page.locator("#snapshot-1").getByTestId("snapshot-jump")).toBeFocused();
});

test("publication shows a collapsed analysis card that expands and marks signals on the charts",async({page})=>{
  await page.goto("/posts/1");
  const card=page.getByTestId("anomaly-card");
  const toggle=page.getByTestId("anomaly-toggle");
  await expect(toggle).toHaveAttribute("aria-expanded","false");
  await expect(toggle).toContainText("признаки искусственной активности");
  await expect(toggle).toContainText("2 признака");
  await expect(card.getByTestId("anomaly-signal")).toHaveCount(0);
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded","true");
  await expect(card.getByTestId("anomaly-signal")).toHaveCount(2);
  await expect(card.locator("code").first()).toContainText("Δпросмотры ≈ 10·t");
  await expect(card).toContainText("пост долго показывался в рекомендациях");
  // Справка — под значком «i», а не в теле карточки.
  await expect(card.getByTestId("anomaly-quality")).toHaveCount(0);
  await card.getByTestId("anomaly-note").getByRole("button").hover();
  await expect(page.getByLabel("Значки признаков")).toContainText("линейная подача");
  await expect(page.getByTestId("anomaly-quality")).toBeVisible();
  await page.mouse.move(0,0);
  // Значки признаков стоят на обоих основных графиках, по одному на признак.
  await expect(page.locator('[role="img"][data-chart-ready="true"]')).toHaveCount(2,{timeout:15_000});
  await expect(page.locator("g[data-signal-marker]")).toHaveCount(4);
  await expect(page.locator("g[data-signal-marker] svg.lucide").first()).toBeAttached();
  await card.getByRole("button",{name:"Показать на графике"}).first().click();
  await expect(page.locator("g[data-signal-marker][data-highlighted]")).toHaveCount(2);
  await expect(page.getByTestId("publication-chart-stack")).toBeInViewport();
  await page.getByRole("link",{name:"загрузить всю историю"}).click();
  await expect(page).toHaveURL(/history_limit=3000$/);
  await expect(page.locator("#snapshot-40[data-anomaly-boundary]")).toContainText("граница сигнала аномальной динамики");
  await expect(page.locator("#snapshot-41[data-anomaly-boundary]")).toContainText("граница сигнала аномальной динамики");
});

test("account table shows the analysis level without waiting for it",async({page})=>{
  await page.goto("/channels/1");
  await expect(page.getByRole("columnheader",{name:"Анализ динамики"})).toBeVisible();
  const cells=page.getByTestId("anomaly-level-cell");
  await expect(cells).toHaveCount(2);
  await expect(cells.nth(0)).toContainText("выраженная аномалия");
  await expect(cells.nth(0).locator("svg.lucide")).toHaveCount(1);
  await expect(cells.nth(1)).toContainText("ожидает");
});

test("a post without signals reads calmly and an unanalyzed post says so",async({page})=>{
  await page.goto("/posts/3");
  await expect(page.getByTestId("anomaly-toggle")).toContainText("Нет признаков");
  await expect(page.getByTestId("anomaly-toggle").locator('[data-slot="badge"]')).toHaveCount(0);
  await page.goto("/posts/2");
  await expect(page.getByTestId("anomaly-toggle")).toContainText("Ещё не проанализирован");
});

test("cumulative and delta charts both draw when anomaly boundaries size points per sample",async({page})=>{
  await page.goto("/posts/1");
  // A per-sample point size once collapsed the whole line geometry to NaN and
  // left the cumulative plot blank while the bar plot still drew.
  await expect.poll(async()=>page.evaluate(()=>{
    const plots=[...document.querySelectorAll('[role="img"][data-chart-ready="true"] svg.recharts-surface')];
    return {
      count:plots.length,
      allDrawn:plots.length===2&&plots.every(svg=>svg.querySelectorAll("path.recharts-curve, path.recharts-area-area, path.recharts-rectangle, rect.recharts-rectangle").length>0),
      anyBroken:plots.some(svg=>[...svg.querySelectorAll("path[d]")].some(path=>/NaN|Infinity/.test(path.getAttribute("d")??""))),
    };
  }),{timeout:15_000}).toEqual({count:2,allDrawn:true,anyBroken:false});
});

test("a long interval between saved changes is spaced by time without claiming collector downtime",async({page})=>{
  await page.goto("/posts/7");
  await expect(page.getByTestId("sparse-history-note")).toContainText("не означает, что сборщик не работал");
  await expect(page.getByTestId("saved-history-note")).toContainText("могли быть успешные опросы с теми же значениями");
  await expect(page.getByTestId("collector-gap-summary")).toContainText("подтверждённых пропусков в выбранном диапазоне нет");
  await expect(page.locator(".collector-gap")).toHaveCount(0);
  await expect(page.getByTestId("collector-covered-badge").first()).toHaveText("Сбор шёл");
  const longInterval=page.getByTestId("saved-point-interval").filter({hasText:"+2 д 13 ч"});
  const longIntervalRow=longInterval.locator("..").locator("..");
  await expect(longInterval).toHaveText("+2 д 13 ч");
  await expect(longIntervalRow).not.toHaveAttribute("title");
  await expect(longIntervalRow.locator('[title="exact"]')).toHaveCount(0);
  await expect(longIntervalRow).not.toContainText("между точками");
  await expect(longIntervalRow).not.toContainText("Успешных циклов:");
  expect((await longIntervalRow.boundingBox())!.height).toBeLessThan(45);
  await longInterval.hover();
  await expect(page.getByRole("tooltip").filter({hasText:"Это не простой: опросы без изменений не сохраняются"})).toBeVisible();
  await longIntervalRow.getByTestId("collector-status-trigger").hover();
  await expect(page.getByRole("tooltip").filter({hasText:"успешных циклов — 732, с ошибкой — 0"})).toBeVisible();
  await expect(page.locator('[role="img"][data-chart-ready="true"]')).toHaveCount(2,{timeout:15_000});
  // Neighbouring samples across the break are placed far apart, not side by
  // side: the plotted geometry leaves a wide horizontal stretch between two
  // consecutive samples of the series.
  const spacing=await page.evaluate(async()=>{
    await new Promise(resolve=>setTimeout(resolve,600));
    const plot=document.querySelector('[role="img"][data-chart-ready="true"] svg')!;
    const curve=plot.querySelector("path.recharts-curve[d], path.recharts-area-area[d]")!;
    // Каждая команда пути заканчивается координатами вершины — реального
    // замера, — будь то отрезок или кубическая кривая сглаженной линии.
    const xs=[...((curve.getAttribute("d")??"").match(/[A-Za-z][^A-Za-z]*/g)??[])].flatMap(command=>{
      const numbers=[...command.matchAll(/-?[\d.]+/g)].map(match=>Number(match[0]));
      return numbers.length>=2 ? [numbers[numbers.length-2]!] : [];
    });
    let widest=0;
    for(let index=1;index<xs.length;index++) widest=Math.max(widest,Math.abs(xs[index]!-xs[index-1]!));
    return {widest,span:Math.max(...xs)-Math.min(...xs)};
  });
  expect(spacing.span).toBeGreaterThan(100);
  expect(spacing.widest).toBeGreaterThan(spacing.span/8);
});

test("a confirmed account-cycle outage is marked in both charts and the table",async({page})=>{
  await page.goto("/posts/8");
  await expect(page.getByTestId("collector-gap-summary")).toContainText("Подтверждённые пропуски сбора");
  await expect(page.getByTestId("collector-gap-summary")).toContainText("50 мин");
  await expect(page.getByTestId("collector-gap-badge")).toHaveCount(1);
  await expect(page.getByTestId("collector-gap-badge")).toHaveText("Пропуск 50 мин");
  await expect(page.locator('[role="img"][data-chart-ready="true"]')).toHaveCount(2,{timeout:15_000});
  await expect(page.locator(".collector-gap")).toHaveCount(2);
});

test("publication page with the expanded analysis card meets axe AA and exposes non-color boundary text",async({page})=>{
  await page.goto("/posts/1");
  await page.getByTestId("anomaly-toggle").click();
  await expect(page.getByTestId("anomaly-signal")).toHaveCount(2);
  await page.getByRole("link",{name:"загрузить всю историю"}).click();
  await expect(page).toHaveURL(/history_limit=3000$/);
  await expect(page.locator("[data-anomaly-boundary] .sr-only").first()).toHaveText(", граница сигнала аномальной динамики");
  expect((await new AxeBuilder({page}).withTags(["wcag2a","wcag2aa","wcag21aa"]).analyze()).violations).toEqual([]);
});

test("a long history arrives as a preview and loads the rest on the first zoom",async({page,request})=>{
  test.setTimeout(60_000);
  // В проде /api/v1 отдаёт nginx; у стенда API — отдельный процесс фикстуры.
  await page.route("**/api/v1/**",(route)=>route.continue({url:route.request().url().replace(/^http:\/\/[^/]+/,"http://127.0.0.1:18091")}));
  const preview=await (await request.get("/posts/99")).text();
  const full=await (await request.get("/posts/99?history_limit=3000")).text();
  // Сервер рисует двадцать строк таблицы и отдаёт выборку, а не 1205 точек.
  expect(preview.match(/<tr id="snapshot-/g)?.length).toBe(20);
  expect(preview.length).toBeLessThan(full.length*0.4);
  expect(preview).not.toContain("fixture-");
  await page.goto("/posts/99");
  const chart=page.getByRole("img",{name:"Накопление показателей",exact:true});
  await expect(chart).toHaveAttribute("data-chart-ready","true",{timeout:30_000});
  await expect(page.locator("tbody tr")).toHaveCount(100);
  await expect(page.getByTestId("chart-range-head")).toContainText("1205 сохранённых точек");
  const loaded=page.waitForRequest(/\/api\/v1\/publications\/[0-9a-f-]{36}\/history\?limit=3000$/);
  await page.getByRole("slider",{name:"Начало диапазона"}).focus();
  await page.keyboard.press("End");
  await loaded;
  await expect(page.getByTestId("full-history-loading")).toHaveCount(0);
  await expect(page.getByTestId("chart-range-head")).not.toContainText("1205 сохранённых точек");
  await expect(chart).toHaveAttribute("data-chart-ready","true");
  await expect(page.locator("tbody tr")).toHaveCount(100);
});

test("a point older than the 1000-row boundary remains reachable and the next publication resets its range",async({page}) => {
  test.setTimeout(60_000);
  await page.goto("/posts/99");
  await page.getByRole("link",{name:"загрузить всю историю"}).click();
  await expect(page).toHaveURL(/history_limit=3000$/);
  const chart=page.getByRole("img",{name:"Накопление показателей",exact:true});
  // Hydrating 1205 native table rows precedes the lazy renderer on CI's shared
  // CPU. This is a reachability test; measured latency has a separate gate.
  await expect(chart).toHaveAttribute("data-chart-ready","true",{timeout:30_000});
  await expect(page.locator("tbody tr")).toHaveCount(1205);
  await chart.focus();await page.keyboard.press("Home");await page.keyboard.press("Enter");
  await expect(page.locator("tbody tr")).toHaveCount(1205);
  await expect(page.locator("#snapshot-1")).toBeInViewport();
  await page.locator('a[rel="next"]').click();
  // The table still pages at a hundred rows, while the chart covers every sample
  // the database holds for the publication.
  await expect(page.locator("tbody tr")).toHaveCount(100);
  await expect(page.getByRole("img",{name:"Накопление показателей",exact:true})).toHaveAttribute("data-chart-ready","true");
  await expect(page.getByTestId("chart-range-head")).toContainText("160 сохранённых точек");
  await expect(page.getByRole("link",{name:"загрузить всю историю"})).toBeVisible();
});

test("hundreds of collector gaps use one SVG overlay per chart",async({page})=>{
  await page.goto("/posts/98");
  await expect(page.locator('[role="img"][data-chart-ready="true"]')).toHaveCount(2,{timeout:15_000});
  await expect(page.getByTestId("collector-gap-summary")).toContainText("800");
  const overlays=page.locator(".collector-gap");
  await expect(overlays).toHaveCount(2);
  await expect(overlays.first()).toHaveAttribute("data-gap-count","800");
  await expect(overlays.first()).toHaveAttribute("data-gap-blocks","1");
});

test("hidden labels deep in the history table do not stretch the page below it",async({page})=>{
  await page.goto("/posts/1?history_limit=3000");
  await expect(page.locator("#snapshot-40[data-anomaly-boundary]")).toHaveCount(1);
  const gap=await page.evaluate(()=>document.documentElement.scrollHeight-(document.querySelector("main")!.getBoundingClientRect().bottom+window.scrollY));
  // Под main — только подвал; тысяч пикселей пустоты быть не должно.
  expect(gap).toBeLessThan(200);
});
