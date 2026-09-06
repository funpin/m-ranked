import { chromium } from "@playwright/test";
import { readFile,mkdir,writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { createHash } from "node:crypto";
import assert from "node:assert/strict";
import { visualInitScript,readVisualState,settleLegacyCharts,mobileObserverInit,readMobileMetrics } from "./browser-instrumentation.mjs";

const legacy=process.env.LEGACY_BASE_URL,target=process.env.TARGET_BASE_URL,manifest=process.env.VISUAL_FIXTURE_MANIFEST,runtimePath=process.env.VISUAL_RUNTIME_EVIDENCE,dist=process.env.NEXT_DIST_DIR;
if(!legacy||!target||!manifest||!runtimePath||!dist)throw new Error("Both origins, fixture, runtime evidence and production artifact are required");
const fixture=JSON.parse(await readFile(manifest,"utf8")),runtime=JSON.parse(await readFile(runtimePath,"utf8"));
const hash=(value:string|Buffer)=>createHash("sha256").update(value).digest("hex");
assert.equal(hash(await readFile(fixture.path)),fixture.sha256);assert.equal(fixture.sha256,runtime.sourceSha256);
const revision=async()=>{const response=await fetch(new URL("/api/v1/revision",runtime.apiBaseUrl));assert.equal(response.status,200);return response.json();};
const before=await revision();assert.equal(before.datasetRevision,runtime.database.datasetRevision);assert.equal(before.representationVersion,runtime.revision.representationVersion);
const output=resolve(process.env.TOOLTIP_OUTPUT??"evidence/chart-null-tooltip");await mkdir(output,{recursive:true});
const traceInit={content:`(() => {
  const fill = CanvasRenderingContext2D.prototype.fillText, clear = CanvasRenderingContext2D.prototype.clearRect;
  window.__chartTextFrames = {};
  CanvasRenderingContext2D.prototype.clearRect = function(...args) {
    const index = [...document.querySelectorAll("canvas")].indexOf(this.canvas);
    if (index >= 0) window.__chartTextFrames[index] = [];
    return Reflect.apply(clear, this, args);
  };
  CanvasRenderingContext2D.prototype.fillText = function(...args) {
    const index = [...document.querySelectorAll("canvas")].indexOf(this.canvas);
    if (index >= 0) (window.__chartTextFrames[index] ??= []).push(String(args[0]));
    return Reflect.apply(fill, this, args);
  };
})();`};
const browser=await chromium.launch(),results=[];
let selection:{datasetIndex:number;dataIndex:number;label:string;rawValue:null;x:number;y:number;width:number;height:number}|undefined;
try {
  // Exercise a real positive layout shift, not merely a successfully set zero.
  const observerContext=await browser.newContext({viewport:{width:1000,height:800}});
  await observerContext.addInitScript(visualInitScript(fixture.clock));
  const observerPage=await observerContext.newPage();
  await observerPage.goto("data:text/html,<div id='spacer'></div><h1>Observed layout shift</h1>");
  await observerPage.waitForTimeout(200);await observerPage.evaluate("document.getElementById('spacer').style.height='200px'");await observerPage.waitForTimeout(200);
  const observedShift=await readVisualState(observerPage,fixture.clock);assert.ok(observedShift.cls>0,"A real layout shift must be observed");
  results.push({scope:"native visual observer smoke",observedShift});await observerContext.close();
  const mobileContext=await browser.newContext();await mobileContext.addInitScript(mobileObserverInit);
  const mobilePage=await mobileContext.newPage();await mobilePage.goto("data:text/html,<h1>Mobile observer smoke</h1><button>Real input</button>");
  await mobilePage.evaluate("document.querySelector('button').onclick=()=>{const start=performance.now();while(performance.now()-start<50){};document.querySelector('h1').textContent='Updated by real input'}");
  await mobilePage.waitForTimeout(200);await mobilePage.getByRole("button",{name:"Real input"}).click();await mobilePage.waitForTimeout(200);
  const observedMobile=await readMobileMetrics(mobilePage);assert.ok(observedMobile.lcp>0);assert.ok(Object.values(observedMobile.interactions).some(value=>value>=40));
  results.push({scope:"native mobile observer smoke; no performance acceptance",observedMobile});await mobileContext.close();

  for(const [side,origin] of [["legacy",legacy],["target",target]] as const){
    const context=await browser.newContext({viewport:{width:1440,height:900},deviceScaleFactor:1,locale:"ru-RU",timezoneId:"Europe/Moscow"});
    await context.route("https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js",route=>route.fulfill({path:resolve("node_modules/chart.js/dist/chart.umd.js"),contentType:"application/javascript"}));
    await context.addInitScript(visualInitScript(fixture.clock));await context.addInitScript(traceInit);
    const page=await context.newPage(),errors:string[]=[];page.on("pageerror",error=>errors.push(error.message));
    assert.equal((await page.goto(new URL("/platform-posts/1",origin).toString(),{waitUntil:"networkidle"}))?.status(),200);
    await page.evaluate(()=>document.fonts.ready);
    await page.waitForFunction(()=>[...document.querySelectorAll("canvas[data-chart-ready]")].every(canvas=>canvas.getAttribute("data-chart-ready")==="true"));
    const instrumentation=await readVisualState(page,fixture.clock);await settleLegacyCharts(page);
    const canvas=page.locator("canvas").nth(1);await canvas.evaluate(element=>element.scrollIntoView({block:"start"}));
    const box=(await canvas.boundingBox())!;
    if(side==="legacy"){
      selection=await page.evaluate(`(() => {
        const chart = Object.values(window.Chart.instances)[1];
        for (const [datasetIndex, dataset] of chart.data.datasets.entries()) {
          if (!chart.isDatasetVisible(datasetIndex)) continue;
          const dataIndex = dataset.data.findIndex(value => value === null);
          if (dataIndex < 0) continue;
          const point = chart.getDatasetMeta(datasetIndex).data[dataIndex];
          return { datasetIndex, dataIndex, label: dataset.label, rawValue: dataset.data[dataIndex], x: point.x,
            y: Math.max(chart.chartArea.top+2,Math.min(chart.chartArea.bottom-2,Number.isFinite(point.base)?point.base:point.y)),width:chart.width,height:chart.height };
        }
        throw new Error("The visible native bar fixture must contain a null point");
      })()`);
    }
    assert.ok(selection&&Number.isFinite(selection.x)&&Number.isFinite(selection.y));
    await page.mouse.move(1,1);await page.mouse.move(box.x+selection.x*box.width/selection.width,box.y+selection.y*box.height/selection.height);
    await page.waitForTimeout(300);
    const texts=await page.evaluate("window.__chartTextFrames[1]") as string[];
    const tooltip=side==="legacy"?await page.evaluate(`(() => {const t=Object.values(window.Chart.instances)[1].tooltip;return {opacity:t.opacity,title:t.title,body:t.body?.flatMap(row=>row.lines),points:t.dataPoints?.map(point=>({datasetIndex:point.datasetIndex,dataIndex:point.dataIndex,raw:point.raw,parsed:point.parsed,formattedValue:point.formattedValue}))};})()`):null;
    await page.screenshot({path:resolve(output,`${side}.png`),fullPage:false,animations:"disabled"});
    const tooltipLines=texts.filter(text=>text.startsWith(`${selection!.label}:`));
    results.push({side,origin,path:"/platform-posts/1",chartIndex:1,selection,instrumentation,errors,texts,tooltipLines,tooltip});
    assert.equal(errors.length,0,"Browser instrumentation and app scripts must not throw");
    assert.ok(tooltipLines.length>0,"The actual pointer tooltip must be painted");
    await context.close();
  }
}finally{await browser.close();}
const after=await revision();assert.deepEqual(after,before);
const sides=results.filter(row=>"side" in row),semanticParity=JSON.stringify(sides[0]!.tooltipLines)===JSON.stringify(sides[1]!.tooltipLines);
const report={generatedAt:new Date().toISOString(),scope:"Actual natural-pointer tooltip over a source null bar, plus browser-native positive CLS and Event Timing smoke. Clock and observer installation are required; only legacy chart animation is disabled for a final endpoint still. Canvas text interception delegates unchanged drawing calls. This is not a performance benchmark or approval of a semantic deviation.",fixture,runtimePath,jarSha256:runtime.jarSha256,buildId:(await readFile(resolve(dist,"BUILD_ID"),"utf8")).trim(),revisionBefore:before,revisionAfter:after,results,semanticParity,ownerDecision:semanticParity?"not needed for this observed state":"pending",approvedDeviation:false,releaseAcceptance:false};
await writeFile(resolve(output,"report.json"),JSON.stringify(report,null,2)+"\n");console.log(JSON.stringify({semanticParity,results:sides.map(row=>({side:row.side,tooltipLines:row.tooltipLines,tooltip:row.tooltip}))},null,2));
