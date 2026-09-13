import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

for(const [path,reaction,hasComments,hasShares] of [
  ["/posts/1","реакций",true,false], ["/platform-posts/21","лайков",true,true],
  ["/platform-posts/1","реакций",true,false], ["/platform-posts/41","лайков",false,false],
] as const) {
  test(`${path} uses shared metrics, ratios and exact growth tooltips`, async({page},testInfo) => {
    await page.goto(path);
    const total=page.getByRole("img",{name:"Накопление показателей",exact:true});
    const growth=page.getByRole("img",{name:"Прирост между замерами",exact:true});
    await expect(total).toHaveAttribute("data-chart-ready","true");
    await expect(page.getByRole("button",{name:"Всего комментариев",exact:true})).toHaveCount(hasComments?1:0);
    await expect(page.getByRole("button",{name:"Всего репостов",exact:true})).toHaveCount(hasShares?1:0);
    await total.focus();await page.keyboard.press("End");
    await expect(page.getByRole("tooltip").first()).toContainText(`${reaction==="лайков"?"Лайки":"Реакции"} / просмотры: 9.75%`);
    await growth.focus();await page.keyboard.press("End");
    await expect(page.getByRole("tooltip")).toContainText(`Прирост ${reaction}: -3`);
    await page.keyboard.press("Escape");
    const box=await growth.boundingBox();expect(box).not.toBeNull();
    // The pointer tooltip is rendered text now, so it is read rather than
    // intercepted on its way to a canvas.
    await growth.hover({position:{x:box!.width-20,y:box!.height/2}});
    await expect(growth.getByText(/^Прирост (реакций|лайков): [+-]?\d/)).toBeVisible();
    await growth.screenshot({path:testInfo.outputPath("growth-tooltip.png")});
  });
}

test("clicking an old chart point expands history and scrolls to the exact row",async({page}) => {
  await page.goto("/posts/1");
  await page.getByRole("link",{name:"загрузить всю историю"}).click();
  await expect(page).toHaveURL(/history_limit=3000$/);
  const total=page.getByRole("img",{name:"Накопление показателей",exact:true});
  await expect(total).toHaveAttribute("data-chart-ready","true");
  await expect(page.locator("tbody tr")).toHaveCount(160);
  const box=await total.boundingBox();expect(box).not.toBeNull();
  await total.click({position:{x:60,y:box!.height-65}});
  const selected=page.locator("tr[data-selected]");
  await expect(selected).toHaveCount(1);
  const id=await selected.getAttribute("id");
  expect(Number(id!.replace("snapshot-",""))).toBeLessThanOrEqual(60);
  await expect(selected).toBeInViewport();
  await expect(selected.locator("button")).toBeFocused();
  // Keyboard activation uses the same reveal-and-scroll path after collapsing.
  await page.getByRole("button",{name:"свернуть историю"}).click();
  await expect(page.locator("tbody tr")).toHaveCount(100);
  await total.focus();await page.keyboard.press("Home");await page.keyboard.press("Enter");
  await expect(page.locator("#snapshot-1")).toBeInViewport();
  await expect(page.locator("#snapshot-1 button")).toBeFocused();
});

test("publication presents neutral anomaly evidence and preserves boundary rows",async({page})=>{
  await page.goto("/posts/1");
  const panel=page.getByRole("region",{name:"Сигнал аномальной динамики"});
  await expect(panel).toContainText("Эвристическая сила сигнала: 0.82");
  await expect(panel).toContainText("не доказывает искусственное происхождение");
  await expect(panel).not.toContainText(/вероятность накрутки|мошенничество|накрутка обнаружена/i);
  await page.getByRole("link",{name:"загрузить всю историю"}).click();
  await expect(page).toHaveURL(/history_limit=3000$/);
  await expect(page.locator("#snapshot-40[data-anomaly-boundary]")).toContainText("граница сигнала аномальной динамики");
  await expect(page.locator("#snapshot-41[data-anomaly-boundary]")).toContainText("граница сигнала аномальной динамики");
});

for(const [id,expected,hasPreviousScore] of [[2,"ожидает анализа",false],[3,"частичное покрытие",false],[4,"устарел после ошибки",true],[5,"ошибка анализа",false]] as const) {
  test(`publication anomaly status ${id} is distinct and never rendered as clean zero`,async({page})=>{
    await page.goto(`/posts/${id}`);
    const panel=page.getByRole("region",{name:"Сигнал аномальной динамики"});
    await expect(panel).toContainText(expected);
    if(hasPreviousScore) await expect(panel).toContainText("Эвристическая сила сигнала: 0.52");
    else {
      await expect(panel).toContainText("недостаточно применимых данных");
      await expect(panel).not.toContainText("Эвристическая сила сигнала: 0.00");
    }
  });
}

for(const [path,metric,absent] of [
  ["/platform-posts/21","репосты","комментарии"],["/platform-posts/41","просмотры","репосты"],["/platform-posts/1","комментарии","репосты"],
] as const) {
  test(`${path} anomaly panel names only the provider-supported metric`,async({page})=>{
    await page.goto(path);
    const panel=page.getByRole("region",{name:"Сигнал аномальной динамики"});
    await expect(panel).toContainText(`Затронутые показатели: ${metric}.`);
    await expect(panel).not.toContainText(`Затронутые показатели: ${absent}`);
  });
}

test("cumulative and delta charts both draw when anomaly boundaries size points per sample",async({page})=>{
  await page.goto("/posts/1");
  const drawn=await page.evaluate(async()=>{
    await new Promise(resolve=>setTimeout(resolve,600));
    return [...document.querySelectorAll('[role="img"][data-chart-ready="true"] svg')].map(svg=>({
      shapes:svg.querySelectorAll("path.recharts-curve, path.recharts-area-area, path.recharts-rectangle, rect.recharts-rectangle").length,
      broken:[...svg.querySelectorAll("path[d]")].some(path=>/NaN|Infinity/.test(path.getAttribute("d")??"")),
    }));
  });
  expect(drawn.length).toBe(2);
  // A per-sample point size once collapsed the whole line geometry to NaN and
  // left the cumulative plot blank while the bar plot still drew.
  for(const plot of drawn) {expect(plot.shapes).toBeGreaterThan(0);expect(plot.broken).toBe(false);}
});

test("a break in the observation is spaced by time and marked on the chart",async({page})=>{
  await page.goto("/posts/7");
  const note=page.locator("[data-observation-gaps]");
  await expect(note).toHaveAttribute("data-observation-gaps","1");
  await expect(note).toContainText("Пропуски в наблюдении: 1");
  await expect(note).toContainText("2 д 13 ч");
  // Neighbouring samples across the break are placed far apart, not side by
  // side: the plotted geometry leaves a wide horizontal stretch between two
  // consecutive samples of the series.
  const spacing=await page.evaluate(async()=>{
    await new Promise(resolve=>setTimeout(resolve,600));
    const plot=document.querySelector('[role="img"][data-chart-ready="true"] svg')!;
    const curve=plot.querySelector("path.recharts-curve[d], path.recharts-area-area[d]")!;
    const xs=[...(curve.getAttribute("d")??"").matchAll(/[ML]\s*(-?[\d.]+)/g)].map(match=>Number(match[1]));
    let widest=0;
    for(let index=1;index<xs.length;index++) widest=Math.max(widest,Math.abs(xs[index]!-xs[index-1]!));
    return {widest,span:Math.max(...xs)-Math.min(...xs)};
  });
  expect(spacing.span).toBeGreaterThan(100);
  expect(spacing.widest).toBeGreaterThan(spacing.span/8);
});

test("publication page with anomaly evidence meets axe AA and exposes non-color boundary text",async({page})=>{
  await page.goto("/posts/1");
  await page.getByRole("link",{name:"загрузить всю историю"}).click();
  await expect(page).toHaveURL(/history_limit=3000$/);
  await page.getByRole("region",{name:"Сигнал аномальной динамики"}).getByRole("group").first().locator("summary").click();
  await expect(page.locator("[data-anomaly-boundary] .sr-only").first()).toHaveText(", граница сигнала аномальной динамики");
  expect((await new AxeBuilder({page}).withTags(["wcag2a","wcag2aa","wcag21aa"]).analyze()).violations).toEqual([]);
});

test("manual unresolved signal stays separate from automatic clean score",async({page})=>{
  await page.goto("/posts/6");
  const panel=page.getByRole("region",{name:"Сигнал аномальной динамики"});
  await expect(panel).toContainText("Эвристическая сила сигнала: 0.00");
  await expect(panel).toContainText("Присутствует отдельная ручная оценка");
  await expect(panel).toContainText("требует проверки");
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
  await expect(page.getByTestId("chart-range-head")).toContainText("160 замеров");
  await expect(page.getByRole("link",{name:"загрузить всю историю"})).toBeVisible();
});
