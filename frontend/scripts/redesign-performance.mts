/** Frontend-only calibration. Uses the explicit synthetic fixture, never claims API/PG acceptance. */
import { chromium } from "@playwright/test";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { gzipSync } from "node:zlib";
import { cpus } from "node:os";
import assert from "node:assert/strict";
import { mobileObserverInit, readMobileMetrics } from "./browser-instrumentation.mjs";

const origin = process.env.PERFORMANCE_BASE_URL ?? "http://127.0.0.1:18092";
const dist = process.env.NEXT_DIST_DIR ?? ".next-browser-tests";
const buildId = (await readFile(`${dist}/BUILD_ID`, "utf8")).trim();
const directory = "reports/redesign";
await mkdir(directory, { recursive: true });
const paths = ["/?platform=telegram", "/?platform=all", "/rating?platform=telegram", "/compare?platform=vk&period=336", "/publications/00000005-0000-4000-8000-000000000001"];
const rows: {path:string; lcp:number; inp:number; cls:number; initialJsGzipBytes:number; scripts:{url:string;gzipBytes:number;sha256:string}[]; workload:{cards:number;rating:number;charts:number;legends:number}}[] = [];
const browser = await chromium.launch();
const p75 = (values:number[]) => values.toSorted((a,b) => a-b)[Math.ceil(values.length*.75)-1]!;
try {
  for (const path of paths) for (let sample = 0; sample < 5; sample++) {
    const context = await browser.newContext({ viewport:{width:390,height:844},deviceScaleFactor:1,isMobile:true,hasTouch:true,locale:"ru-RU",timezoneId:"Europe/Moscow",colorScheme:"dark" });
    try {
      const page = await context.newPage();
      const cdp = await context.newCDPSession(page);
      await cdp.send("Network.enable");
      await cdp.send("Network.setCacheDisabled",{cacheDisabled:true});
      await cdp.send("Network.emulateNetworkConditions",{offline:false,latency:150,downloadThroughput:1_600_000/8,uploadThroughput:750_000/8,connectionType:"cellular4g"});
      await cdp.send("Emulation.setCPUThrottlingRate",{rate:4});
      const scripts: Promise<{url:string;gzipBytes:number;sha256:string}>[] = [];
      page.on("response", response => {
        if (response.request().resourceType() !== "script") return;
        scripts.push(response.body().then(body => ({ url:response.url(),gzipBytes:gzipSync(body,{level:9}).length,sha256:createHash("sha256").update(body).digest("hex") })));
      });
      await page.addInitScript(mobileObserverInit);
      const response = await page.goto(`${origin}${path}`,{waitUntil:"networkidle",timeout:120_000});
      assert.equal(response?.status(),200);
      if (/\/(compare|publications)/.test(path)) {
        await page.locator('[data-chart-ready="true"] svg.recharts-surface').nth(1).waitFor({timeout:120_000});
        await page.waitForTimeout(600);
      }
      const workload = await page.evaluate(() => ({ cards:document.querySelectorAll('[data-testid="platform-overview-card"]').length,rating:document.querySelector('[data-testid="rating-table"]')?.querySelectorAll('tbody tr').length??0,charts:document.querySelectorAll('[data-chart-ready="true"] svg.recharts-surface').length,legends:document.querySelectorAll('[data-testid="comparison-legend-toggle"]').length }));
      if (path.startsWith('/?')) assert.equal(workload.cards,50);
      if (path.startsWith('/rating')) assert.equal(workload.rating,200);
      if (path.startsWith('/compare')) { assert.equal(workload.charts,2);assert.equal(workload.legends,207); }
      const initialScripts = await Promise.all(scripts);
      // Theme chunks requested by the interaction are intentionally outside initial payload.
      await page.getByRole("button",{name:/Тема:/}).click();
      await page.getByRole("menuitemradio",{name:"Светлая"}).click();
      await page.keyboard.press("Escape");
      await page.getByRole("menu").waitFor({state:"hidden"});
      await page.getByRole("button",{name:/Тема:/}).click();
      await page.getByRole("menuitemradio",{name:"Тёмная"}).click();
      await page.keyboard.press("Escape");
      await page.getByRole("menu").waitFor({state:"hidden"});
      const legend = page.getByTestId("comparison-legend-toggle").nth(1);
      if (await legend.count()) { await legend.click();await page.waitForTimeout(1000);await legend.click();await page.waitForTimeout(1000); }
      const chart = page.locator('[data-chart-ready="true"][tabindex]').first();
      if (await chart.count()) { await chart.focus();await chart.press("ArrowRight");await chart.press("End");await chart.press("Escape"); }
      const auto = page.getByRole("button",{name:"Авто",exact:true}).first();
      if (await auto.count()) { await auto.click();await page.getByRole("button",{name:"1:1",exact:true}).first().click(); }
      await page.waitForTimeout(300);
      const metrics = await readMobileMetrics(page);
      assert.equal(metrics.supported,true);
      assert.ok(metrics.lcp > 0);
      const durations = Object.values(metrics.interactions).sort((a,b)=>b-a);
      const inp = durations[Math.floor(durations.length/50)] ?? 0;
      rows.push({path,lcp:metrics.lcp,inp,cls:metrics.cls,initialJsGzipBytes:initialScripts.reduce((sum,row)=>sum+row.gzipBytes,0),scripts:initialScripts,workload});
      console.log(JSON.stringify({path,sample:sample+1,lcp:metrics.lcp,inp,cls:metrics.cls,workload}));
      await writeFile(`${directory}/calibration-progress.json`,JSON.stringify(rows,null,2)+"\n");
    } finally { await context.close(); }
  }
} finally { await browser.close(); }
const summaries=paths.map(path=>{
  const samples=rows.filter(row=>row.path===path);
  return {path,samples:samples.length,lcpP75Ms:p75(samples.map(row=>row.lcp)),inpP75Ms:p75(samples.map(row=>row.inp)),clsP75:p75(samples.map(row=>row.cls)),initialJsGzipBytes:Math.max(...samples.map(row=>row.initialJsGzipBytes))};
});
await writeFile(`${directory}/calibration.json`,JSON.stringify({generatedAt:new Date().toISOString(),buildId,browser:browser.version(),cpu:cpus()[0]?.model,scope:"Frontend-only synthetic calibration: 50 overview cards, 200 rating entities, 207 comparison series × 337 hours in each of two SVG plots, 160 publication observations. API test double; no PostgreSQL, quiet-host or production acceptance claim. Initial payload includes dynamically loaded plots; theme menu loads on interaction.",productionAcceptance:false,throttling:{cpu:4,latencyMs:150,downloadBitsPerSecond:1600000},summaries,rows},null,2)+"\n");
console.log(JSON.stringify(summaries,null,2));
