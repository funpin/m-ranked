import { chromium } from "@playwright/test";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { createHash } from "node:crypto";
import { gzipSync } from "node:zlib";
import assert from "node:assert/strict";
import { isDeepStrictEqual } from "node:util";
import { arch,cpus,loadavg,platform,release,totalmem } from "node:os";
import { mobileObserverInit,readMobileMetrics } from "./browser-instrumentation.mjs";

const budgets = JSON.parse(await readFile(new URL("./performance-budgets.json", import.meta.url), "utf8")) as {
  default: { lcpMs: number; inpMs: number; cls: number; initialJsGzipBytes: number };
  comparison: { lcpMs: number; inpMs: number; cls: number; initialJsGzipBytes: number };
  publication: { lcpMs: number; inpMs: number; cls: number; initialJsGzipBytes: number };
};

const producerFilesSha256=Object.fromEntries(await Promise.all(["mobile-performance.mts", "browser-instrumentation.mts", "performance-budgets.json"].map(async(name)=>[name,createHash("sha256").update(await readFile(new URL(name,import.meta.url))).digest("hex")])));

const origin = process.env.PERFORMANCE_BASE_URL;
const manifest = process.env.VISUAL_FIXTURE_MANIFEST;
if (!origin || !manifest) throw new Error("PERFORMANCE_BASE_URL and VISUAL_FIXTURE_MANIFEST are required");
const fixture = JSON.parse(await readFile(manifest,"utf8"));
const sourceSha256=createHash("sha256").update(await readFile(fixture.path)).digest("hex");
if(sourceSha256!==fixture.sha256) throw new Error("Frozen source changed since its manifest was produced");
const runtimeEvidencePath=process.env.PERFORMANCE_RUNTIME_EVIDENCE;
if(!runtimeEvidencePath||!process.env.API_BASE_URL||!process.env.NEXT_DIST_DIR) throw new Error("PERFORMANCE_RUNTIME_EVIDENCE, API_BASE_URL and NEXT_DIST_DIR are required for runtime provenance");
const runtimeEvidence=JSON.parse(await readFile(runtimeEvidencePath,"utf8"));
const databaseBytes=Number(runtimeEvidence.database?.bytes ?? 0);
const expectedCardinalities={institutions:fixture.counts.institutions,accounts:fixture.counts.platform_accounts,publications:fixture.counts.posts+fixture.counts.platform_posts,snapshots:fixture.counts.reaction_snapshots+fixture.counts.platform_snapshots};
const corpusMatches=Object.entries(expectedCardinalities).every(([key,value])=>runtimeEvidence.database?.[key]===value);
const workloadMinimums={institutions:201,accounts:800,publications:800,snapshots:9000,comparisonPoints:8_000_000};
const representativeWorkload=corpusMatches&&Object.entries(workloadMinimums).every(([key,value])=>Number(runtimeEvidence.database?.[key])>=value);
const revisionUrl=new URL("/api/v1/revision",process.env.API_BASE_URL);
const readRevision=async()=>{const response=await fetch(revisionUrl,{cache:"no-store",signal:AbortSignal.timeout(8000)});if(!response.ok)throw new Error(`Revision HTTP ${response.status}`);return response.json();};
const revisionBefore=await readRevision();
// Reject stale or unrelated runtime evidence before starting fifty browser samples.
assert.equal(runtimeEvidence.sourceSha256,sourceSha256,"Runtime and frozen source must match");
assert.equal(runtimeEvidence.apiBaseUrl,revisionUrl.origin,"Runtime evidence must identify the measured API origin");
assert.equal(revisionBefore.datasetRevision,runtimeEvidence.database?.datasetRevision,"Dataset changed since runtime evidence was recorded");
assert.equal(revisionBefore.representationVersion,runtimeEvidence.revision?.representationVersion,"API representation changed since runtime evidence was recorded");
const buildId=(await readFile(resolve(process.env.NEXT_DIST_DIR,"BUILD_ID"),"utf8")).trim();
const staticRoot=resolve(process.env.NEXT_DIST_DIR,"static"),artifactScriptHashes=new Map<string,Promise<string>>();
async function artifactScriptHash(url:string):Promise<string|null> {
  const parsed=new URL(url);
  if(parsed.origin!==new URL(origin!).origin||!parsed.pathname.startsWith("/_next/static/"))return null;
  const file=resolve(staticRoot,decodeURIComponent(parsed.pathname.slice("/_next/static/".length)));
  if(!file.startsWith(`${staticRoot}/`))return null;
  let pending=artifactScriptHashes.get(file);
  if(!pending){pending=readFile(file).then((bytes)=>createHash("sha256").update(bytes).digest("hex"));artifactScriptHashes.set(file,pending);}
  return pending.catch(()=>null);
}
const bundleRows=JSON.parse(await readFile(resolve(process.env.NEXT_DIST_DIR,"diagnostics/route-bundle-stats.json"),"utf8")) as {route:string;firstLoadChunkPaths:string[]}[];
const nextFirstLoads=await Promise.all(bundleRows.map(async(row)=>({route:row.route,gzipBytes:(await Promise.all([...new Set(row.firstLoadChunkPaths)].map(async(path)=>gzipSync(await readFile(path),{level:9}).length))).reduce((sum,value)=>sum+value,0)})));
const nextFirstLoad=(path:string)=>nextFirstLoads.find((row)=>new RegExp(`^${row.route.replace(/\[[^/]+\]/g,"[^/]+")}$`).test(new URL(path,origin).pathname))?.gzipBytes??null;
const sampleCount = Number(process.env.PERFORMANCE_SAMPLES ?? 10);
if (!Number.isSafeInteger(sampleCount) || sampleCount < 5) throw new Error("Use at least five independent cold samples per route");
const paths = JSON.parse(process.env.PERFORMANCE_ROUTES ?? '["/?platform=telegram","/?platform=all","/rating?platform=telegram","/compare?platform=vk","/posts/1"]') as string[];
const directory = resolve(process.env.PERFORMANCE_OUTPUT ?? "reports/mobile-performance");
await mkdir(directory,{recursive:true});
const producerSha256=createHash("sha256").update(await readFile(new URL(import.meta.url))).digest("hex");
const instrumentationSha256=createHash("sha256").update(await readFile(new URL("./browser-instrumentation.mts",import.meta.url))).digest("hex");
const host={platform:platform(),osRelease:release(),architecture:arch(),cpuModel:cpus()[0]?.model??null,logicalCpus:cpus().length,memoryBytes:totalmem(),nodeVersion:process.versions.node,loadAverageBefore:loadavg()};
const browser = await chromium.launch();
const browserVersion=browser.version();
const rows: Record<string,unknown>[] = [];
const p75 = (values:number[]) => [...values].sort((a,b) => a-b)[Math.ceil(values.length*.75)-1] ?? null;
try {
  for (const path of paths) for (let sample=0;sample<sampleCount;sample++) {
    const context = await browser.newContext({ viewport:{width:390,height:844},deviceScaleFactor:1,isMobile:true,hasTouch:true,locale:"ru-RU",timezoneId:"Europe/Moscow",colorScheme:"dark" });
    const page = await context.newPage();
    const cdp = await context.newCDPSession(page);
    await cdp.send("Network.enable");
    await cdp.send("Network.setCacheDisabled",{cacheDisabled:true});
    await cdp.send("Network.emulateNetworkConditions",{offline:false,latency:150,downloadThroughput:1_600_000/8,uploadThroughput:750_000/8,connectionType:"cellular4g"});
    await cdp.send("Emulation.setCPUThrottlingRate",{rate:4});
    const scripts = new Map<string,string>();let transferredScriptBytes=0;
    const speculativeRequests=new Set<string>();
    cdp.on("Network.requestWillBeSent",(event)=>{const headers=Object.fromEntries(Object.entries(event.request.headers).map(([key,value])=>[key.toLowerCase(),String(value)]));if(/prefetch/i.test(`${headers.purpose??""} ${headers["sec-purpose"]??""}`)||headers["next-router-prefetch"]==="1")speculativeRequests.add(event.requestId);});
    const scriptReads:Promise<{url:string;gzipBytes:number;sha256:string;speculativePrefetch:boolean}>[]=[];
    cdp.on("Network.responseReceived",(event) => { if(event.type === "Script") scripts.set(event.requestId,event.response.url); });
    cdp.on("Network.loadingFinished",(event) => { if(scripts.has(event.requestId)) {
      transferredScriptBytes+=event.encodedDataLength;
      scriptReads.push(cdp.send("Network.getResponseBody",{requestId:event.requestId}).then((response)=>{
        const body=Buffer.from(response.body,response.base64Encoded?"base64":"utf8");
        return {url:scripts.get(event.requestId)!,gzipBytes:gzipSync(body,{level:9}).length,sha256:createHash("sha256").update(body).digest("hex"),speculativePrefetch:speculativeRequests.has(event.requestId)};
      }).catch(()=>({url:scripts.get(event.requestId)!,gzipBytes:NaN,sha256:"BODY_READ_FAILED",speculativePrefetch:speculativeRequests.has(event.requestId)})));
    } });
    await page.addInitScript(mobileObserverInit);
    let failure:string|undefined;
    try {
      const response=await page.goto(new URL(path,origin).toString(),{waitUntil:"networkidle",timeout:90_000});
      if(response?.status() !== 200) throw new Error(`HTTP ${response?.status()}`);
      await readMobileMetrics(page);
      if (/\/(compare|posts|publications|platform-posts)(\/|$)/.test(new URL(path, origin).pathname)) {
        await page.waitForFunction(() => document.querySelectorAll('[data-chart-ready="true"] svg.recharts-surface').length === 2);
      }
      // A streamed API failure can retain HTTP 200. It must never look like a fast page.
      const renderedContent=await page.evaluate(()=>({
        deviceScaleFactor:window.devicePixelRatio,
        apiFailure:document.body.innerText.includes("Сервис временно недоступен"),
        overviewCards:document.querySelectorAll('[data-testid="platform-overview-card"]').length,
        ratingEntities:document.querySelector('[data-testid="rating-table"]')?.querySelectorAll('tbody [data-testid="rating-entity-link"]').length??0,
        readyCharts:document.querySelectorAll('[data-chart-ready="true"]').length,
        comparisonCandidates:document.querySelectorAll('input[type="checkbox"][name="institutions"]').length,
        comparisonSelected:document.querySelectorAll('input[type="checkbox"][name="institutions"]:checked').length,
        comparisonLegends:document.querySelectorAll('[data-testid="comparison-legend-toggle"]').length,
        historyRows:document.querySelectorAll('[data-testid="snapshot-history-table"] tbody tr').length,
      }));
      assert.equal(renderedContent.apiFailure,false,"API fallback cannot be measured as a successful page");
      const pageUrl=new URL(path,origin);
      if(pageUrl.pathname==="/")assert.equal(renderedContent.overviewCards,50,"Measure the complete initial overview page");
      if(pageUrl.pathname==="/rating")assert.equal(renderedContent.ratingEntities,200,"Measure the complete initial rating page");
      if(pageUrl.pathname==="/compare"){
        assert.equal(renderedContent.readyCharts,2,"Both comparison charts must be rendered");
        assert.ok(renderedContent.comparisonCandidates>200,"The representative comparison must traverse more than 200 candidates");
        assert.equal(renderedContent.comparisonSelected,renderedContent.comparisonCandidates,"Default comparison must select every candidate");
        assert.equal(renderedContent.comparisonLegends,renderedContent.comparisonCandidates,"Every selected series must be present");
      }
      if(/\/(posts|publications|platform-posts)\//.test(pageUrl.pathname)){
        assert.equal(renderedContent.readyCharts,2,"Both publication charts must be rendered");
        assert.ok(renderedContent.historyRows>0,"Publication observations must be present");
      }
      const initialScriptBytes=transferredScriptBytes;
      const initialScripts=await Promise.all((await Promise.all(scriptReads)).map(async(row)=>{
        const artifactSha256=await artifactScriptHash(row.url);
        return {...row,artifactSha256,artifactMatches:artifactSha256!==null&&artifactSha256===row.sha256};
      }));
      if(!initialScripts.length||initialScripts.some((row)=>!Number.isFinite(row.gzipBytes)))throw new Error("Initial script payload sizes could not be measured");
      if(initialScripts.some((row)=>!row.artifactMatches))throw new Error("Browser received initial JavaScript outside the recorded production artifact");
      const initialScriptGzipBytes=initialScripts.filter((row)=>!row.speculativePrefetch).reduce((sum,row)=>sum+row.gzipBytes,0);
      const speculativeScriptGzipBytes=initialScripts.filter((row)=>row.speculativePrefetch).reduce((sum,row)=>sum+row.gzipBytes,0);
      const development=await page.evaluate(() => performance.getEntriesByType("resource").some((row) => /webpack-hmr|\/_next\/development\//.test(row.name)));
      // Genuine input events include a theme change, menu navigation, typing and chart selection.
      await page.getByRole("button",{name:/Тема:/}).click();
      await page.getByRole("menuitemradio",{name:"Светлая"}).click();
      await page.keyboard.press("Escape");
      await page.getByRole("menu").waitFor({state:"hidden"});
      await page.getByRole("button",{name:/Тема:/}).click();
      await page.getByRole("menuitemradio",{name:"Тёмная"}).click();
      await page.keyboard.press("Escape");
      await page.getByRole("menu").waitFor({state:"hidden"});
      const search=page.locator('input[type="search"]').first();
      if(await search.count()) { await search.fill("Университет");await search.press("ArrowLeft");await search.press("Backspace"); }
      const chart=page.locator('[data-chart-ready="true"][tabindex]').first();
      if(await chart.count()) { await chart.focus();await chart.press("ArrowRight");await chart.press("End");await chart.press("Escape"); }
      const legend=page.locator('[data-testid="comparison-legend-toggle"]').nth(1);
      if(await legend.count()){await legend.click();await legend.click();}
      const independent=page.getByRole("button",{name:"Авто",exact:true}).first();
      if(await independent.count()){await independent.click();await page.getByRole("button",{name:"1:1",exact:true}).first().click();}
      const menu=page.getByRole("button",{name:/Открыть меню/});
      if(await menu.count()) {await menu.click();await page.keyboard.press("Escape");}
      await page.waitForTimeout(300); // Event Timing delivery follows the browser's next presentation.
      const metrics=await readMobileMetrics(page);
      if(!metrics.supported||!Number.isFinite(metrics.lcp)||metrics.lcp<=0) throw new Error("Required browser performance entries were not observed");
      const durations=Object.values(metrics.interactions).sort((a,b)=>b-a);
      // Event Timing only emits >=16ms. All exercised interactions below that threshold imply INP<16ms.
      const inp=durations[Math.floor(durations.length/50)] ?? 0;
      rows.push({path,sample,status:200,instrumentationInitialized:metrics.initialized,renderedContent,lcp:metrics.lcp,inp,inpBelow16ms:durations.length===0,cls:metrics.cls,interactionDurations:metrics.interactions,initialScriptBytes,initialScriptGzipBytes,speculativeScriptGzipBytes,allInitialScriptGzipBytes:initialScriptGzipBytes+speculativeScriptGzipBytes,nextFirstLoadGzipBytes:nextFirstLoad(path),initialScripts,development});
    } catch(error) {failure=error instanceof Error ? error.message : String(error);rows.push({path,sample,failure});}
    finally {await context.close();}
    console.log(`${path} sample ${sample+1}/${sampleCount}${failure ? ` FAILED: ${failure}` : " measured"}`);
    await writeFile(resolve(directory,"progress.json"),JSON.stringify(rows,null,2));
  }
} finally {await browser.close();}
const revisionAfter=await readRevision();
const coherent=isDeepStrictEqual(revisionBefore,revisionAfter)&&revisionBefore.datasetRevision===runtimeEvidence.database.datasetRevision&&runtimeEvidence.sourceSha256===sourceSha256&&runtimeEvidence.apiBaseUrl===revisionUrl.origin&&runtimeEvidence.revision?.representationVersion===revisionBefore.representationVersion;
const hostQuietConfirmed=process.env.PERFORMANCE_HOST_QUIET_CONFIRMED==="true";
const eligibility=representativeWorkload && process.env.PERFORMANCE_BUILD_MODE === "production"&&coherent&&hostQuietConfirmed;
const summaries=paths.map((path) => {
  const samples=rows.filter((row)=>row.path===path);
  const valid=samples.filter((row)=>typeof row.lcp==="number");
  const lcp=p75(valid.map((row)=>row.lcp as number)),inp=p75(valid.map((row)=>row.inp as number)),cls=p75(valid.map((row)=>row.cls as number));
  const initialJsGzipBytes=Math.max(...valid.map((row)=>row.initialScriptGzipBytes as number),0);
  const pathname = new URL(path, origin).pathname;
  // Accepted SVG tradeoff: hundreds of Recharts lines exceed the retired Canvas
  // interaction budget. Calibration and ~15% headroom are recorded explicitly;
  // this threshold does not claim good field Core Web Vitals.
  const budget = pathname === "/compare" ? budgets.comparison : /\/(posts|publications|platform-posts)\//.test(pathname) ? budgets.publication : budgets.default;
  const passed=eligibility && valid.length===sampleCount && valid.every((row)=>!row.development) && lcp!==null&&lcp<=budget.lcpMs&&inp!==null&&inp<=budget.inpMs&&cls!==null&&cls<=budget.cls&&initialJsGzipBytes<=budget.initialJsGzipBytes;
  return {path,samples:valid.length,lcpP75Ms:lcp,inpP75Ms:inp,clsP75:cls,initialJsGzipBytes,nextFirstLoadGzipBytes:nextFirstLoad(path),speculativeJsGzipBytes:Math.max(...valid.map((row)=>row.speculativeScriptGzipBytes as number),0),budget,initialJsBudgetBytes:budget.initialJsGzipBytes,passed};
});
const report={generatedAt:new Date().toISOString(),producerFilesSha256,producerSha256,instrumentationSha256,host:{...host,loadAverageAfter:loadavg()},origin,apiOrigin:revisionUrl.origin,release:process.env.RELEASE_ID ?? execFileSync("git",["rev-parse","HEAD"],{encoding:"utf8"}).trim(),workingTreeDiff:execFileSync("git",["diff","--stat"],{encoding:"utf8"}).trim(),fixture,sourceSha256,databaseBytes,expectedCardinalities,workloadMinimums,corpusMatches,representativeWorkload,productionAcceptance:false,runtimeEvidence:{path:runtimeEvidencePath,jarSha256:runtimeEvidence.jarSha256,database:runtimeEvidence.database},revisionBefore,revisionAfter,coherent,hostQuietConfirmed,buildId,buildMode:process.env.PERFORMANCE_BUILD_MODE ?? "unverified",scope:"Actual API and production Next artifact identified by the recorded runtime evidence and revision. Synthetic 207-entity representative corpus; database size includes indexes and comparison projections. Workload eligibility uses source-bound row cardinalities, not physical allocation, which changes across fresh imports and vacuum/rebuild history; production workload equivalence has not been established. Mobile lab measurements, not production field Core Web Vitals. Each route has an independent cold browser cache; API cache remains under its runtime policy.",methodology:{cls:"Maximum 5s session window with <1s gaps; excludes hadRecentInput",inp:"Event Timing of exercised theme/menu/search/chart/legend/scale interactions; durations <16ms are below observer threshold",initialJs:"Every script fetched through initial network idle/chart readiness, individually gzip level 9; includes dynamically loaded initial charts. Only requests explicitly marked by Purpose/Sec-Purpose prefetch or Next-Router-Prefetch headers are classified separately; unclassified requests remain included. Next firstLoad diagnostics are reported separately.",sources:["https://web.dev/articles/cls","https://web.dev/articles/inp"]},browser:browserVersion,viewport:{width:390,height:844,deviceScaleFactor:1,isMobile:true,hasTouch:true},locale:"ru-RU",timezoneId:"Europe/Moscow",throttling:{cpu:4,latencyMs:150,downloadBitsPerSecond:1_600_000,uploadBitsPerSecond:750_000},sampleCount,gate:summaries.every((row)=>row.passed)?"PASS":"NO-GO",summaries,rows};
await writeFile(resolve(directory,"report.json"),JSON.stringify(report,null,2)+"\n");
console.log(JSON.stringify({gate:report.gate,summaries},null,2));
if(report.gate!=="PASS") process.exitCode=1;
