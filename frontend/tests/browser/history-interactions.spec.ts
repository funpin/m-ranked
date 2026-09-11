import { expect, test } from "@playwright/test";

for(const [path,reaction,hasComments,hasShares] of [
  ["/posts/1","реакций",true,false], ["/platform-posts/21","лайков",true,true],
  ["/platform-posts/1","реакций",true,false], ["/platform-posts/41","лайков",false,false],
] as const) {
  test(`${path} uses shared metrics, ratios and exact growth tooltips`, async({page},testInfo) => {
    // Observe the text actually painted by the canvas, including pointer tooltips.
    await page.addInitScript(() => {
      const original=CanvasRenderingContext2D.prototype.fillText;
      const texts:string[]=[];
      Object.assign(window,{paintedChartText:texts});
      CanvasRenderingContext2D.prototype.fillText=function(text,x,y,maxWidth) {
        if(this.canvas.getAttribute("role")==="img") {texts.push(text);if(texts.length>4000)texts.splice(0,2000);}
        if(maxWidth===undefined) original.call(this,text,x,y);else original.call(this,text,x,y,maxWidth);
      };
    });
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
    await page.evaluate(()=>{(window as unknown as {paintedChartText:string[]}).paintedChartText.length=0;});
    await growth.hover({position:{x:box!.width-20,y:box!.height/2}});
    await expect.poll(()=>page.evaluate(()=> (window as unknown as {paintedChartText:string[]}).paintedChartText.some(text=>/^Прирост (реакций|лайков): [+-]\d/.test(text)))).toBe(true);
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
  const selected=page.locator("tr.snapshot-highlight");
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


test("a point older than the 1000-row boundary remains reachable and the next publication resets its range",async({page}) => {
  await page.goto("/posts/99");
  await page.getByRole("link",{name:"загрузить всю историю"}).click();
  await expect(page).toHaveURL(/history_limit=3000$/);
  const chart=page.getByRole("img",{name:"Накопление показателей",exact:true});
  await expect(chart).toHaveAttribute("data-chart-ready","true");
  await expect(page.locator("tbody tr")).toHaveCount(1205);
  await chart.focus();await page.keyboard.press("Home");await page.keyboard.press("Enter");
  await expect(page.locator("tbody tr")).toHaveCount(1205);
  await expect(page.locator("#snapshot-1")).toBeInViewport();
  await page.locator('a[rel="next"]').click();
  await expect(page.locator("tbody tr")).toHaveCount(100);
  await expect(page.getByRole("img",{name:"Накопление показателей",exact:true})).toHaveAttribute("data-chart-ready","true");
  await expect(page.locator(".chart-range-head")).toContainText("100 замеров");
});
