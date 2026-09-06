import { chromium, type Page, type BrowserContext } from "@playwright/test";
import { mkdir, readFile, writeFile,stat } from "node:fs/promises";
import { createHash } from "node:crypto";
import { resolve } from "node:path";
import pixelmatch from "pixelmatch";
import { PNG } from "pngjs";
import AxeBuilder from "@axe-core/playwright";
import { visualCredentials,redactVisualEvidence,type VisualCredentials } from "./visual-privacy.mjs";
import {storageValues,pairedStorageMasks,maskedStorageScreenshot} from "./visual-dynamic-values.mjs";
import {readOverviewStatuses,compareOverviewStatuses} from "./overview-semantics.mjs";
import {visualInitScript,readVisualState,settleLegacyCharts,legacyChartStillInit} from "./browser-instrumentation.mjs";

const producerFilesSha256=Object.fromEntries(await Promise.all(["visual-parity.mts", "browser-instrumentation.mts", "overview-semantics.mts", "visual-privacy.mts", "visual-dynamic-values.mts"].map(async(name)=>[name,createHash("sha256").update(await readFile(new URL(name,import.meta.url))).digest("hex")])));

const legacy = process.env.LEGACY_BASE_URL;
const target = process.env.TARGET_BASE_URL;
const captureOnly = process.argv.includes("--capture-legacy");
if (!legacy || (!target && !captureOnly)) throw new Error("Set LEGACY_BASE_URL and TARGET_BASE_URL to servers backed by the same frozen corpus. --capture-legacy records the baseline only.");
const manifestPath = process.env.VISUAL_FIXTURE_MANIFEST;
if (!manifestPath) throw new Error("VISUAL_FIXTURE_MANIFEST is required: evidence must identify its frozen dataset and clock");
const fixture = JSON.parse(await readFile(manifestPath, "utf8")) as { sha256: string; clock: string;path:string };
const sourceSha256=createHash("sha256").update(await readFile(fixture.path)).digest("hex");
if(sourceSha256!==fixture.sha256)throw new Error("Frozen source no longer matches its manifest");
const runtimeEvidencePath=process.env.VISUAL_RUNTIME_EVIDENCE;
const runtimeEvidence=runtimeEvidencePath?JSON.parse(await readFile(runtimeEvidencePath,"utf8")):null;
const buildId=process.env.NEXT_DIST_DIR?(await readFile(resolve(process.env.NEXT_DIST_DIR,"BUILD_ID"),"utf8")).trim():null;
const readRevision=async()=>{if(!runtimeEvidence)return null;const response=await fetch(new URL("/api/v1/revision",runtimeEvidence.apiBaseUrl),{cache:"no-store",signal:AbortSignal.timeout(8000)});if(!response.ok)throw new Error(`Revision HTTP ${response.status}`);return response.json();};
const revisionBefore=await readRevision();
if(runtimeEvidence&&(runtimeEvidence.sourceSha256!==sourceSha256||runtimeEvidence.database.datasetRevision!==revisionBefore?.datasetRevision||runtimeEvidence.revision.representationVersion!==revisionBefore?.representationVersion))throw new Error("Runtime evidence does not match the frozen source and active API representation");
const directory = resolve(process.env.VISUAL_OUTPUT ?? `evidence/visual-${Date.now()}`);
await mkdir(directory, { recursive: true });
const viewports = [{ name: "desktop", width: 1440, height: 900 }, { name: "mobile", width: 390, height: 844 }];
const platforms = ["telegram", "vk", "max", "rutube", "all"];
const routes = platforms.flatMap((platform) => [
  ...["3h", "1d", "7d", "30d"].flatMap((period) => [
    `/?platform=${platform}&period=${period}`, `/rating?platform=${platform}&period=${period}`,
  ]),
  ...[24, 48, 72, 168, 336].map((period) => `/compare?platform=${platform}&period=${period}`),
  `/compare?platform=${platform}&submitted=true`,
  `/?platform=${platform}&q=НетТакогоВуза`,
]);
routes.push("/channels/1", "/posts/1", "/posts/1?history_limit=50", "/posts/1?history_limit=bad", "/institutions/1?platform=telegram", "/institutions/1?platform=all", "/platform-accounts/2", "/platform-posts/1", "/channels/99999999", "/manage");
const selectedRoutes = process.env.VISUAL_ROUTES ? JSON.parse(process.env.VISUAL_ROUTES) as string[] : routes;
const credentialsFile=process.env.VISUAL_ADMIN_CREDENTIALS_FILE;
let credentialEnvironment:NodeJS.ProcessEnv=process.env;
if(credentialsFile){const metadata=await stat(credentialsFile);if((metadata.mode&0o077)!==0)throw new Error("Visual credentials file must be private (mode 0600)");const supplied=JSON.parse(await readFile(credentialsFile,"utf8"));credentialEnvironment={...process.env};for(const key of ["LEGACY_ADMIN_USERNAME","LEGACY_ADMIN_PASSWORD","TARGET_ADMIN_USERNAME","TARGET_ADMIN_PASSWORD"])if(typeof supplied[key]==="string")credentialEnvironment[key]=supplied[key];}
const legacyAdmin=visualCredentials(credentialEnvironment,"LEGACY"),targetAdmin=visualCredentials(credentialEnvironment,"TARGET");
const authenticatedReady=!!legacyAdmin&&(captureOnly||!!targetAdmin);
if(!!legacyAdmin!==!!targetAdmin&&!captureOnly)throw new Error("Provide both LEGACY and TARGET administrator credentials for authenticated parity");
type Scenario={path:string;state:"page"|"manage-overview"|"manage-matrix"|"manage-edit-name"|"chart-dark"|"chart-hover"|"chart-light";authenticated:boolean;chartIndex?:number};
const scenarios:Scenario[]=selectedRoutes.map((path)=>({path,state:"page",authenticated:false}));
const chartStates:Scenario["state"][]=process.env.VISUAL_CHART_VARIANTS?JSON.parse(process.env.VISUAL_CHART_VARIANTS):["chart-dark","chart-hover","chart-light"];
if(chartStates.some((state)=>!["chart-dark","chart-hover","chart-light"].includes(state)))throw new Error("Unknown visual chart state");
if(process.env.VISUAL_CHART_STATES==="true")for(const path of selectedRoutes.filter((path)=>/^\/(compare|posts\/|platform-posts\/)/.test(path)))for(const chartIndex of [0,1])for(const state of chartStates)scenarios.push({path,state,authenticated:false,chartIndex});
if(authenticatedReady)scenarios.push(...(["manage-overview","manage-matrix","manage-edit-name"] as const).map((state)=>({path:"/manage?institution_id=1",state,authenticated:true})));
const browser = await chromium.launch();
const results: Record<string,unknown>[] = [];
const fullScope=!process.env.VISUAL_ROUTES;
let failed = !captureOnly&&fullScope&&!authenticatedReady;

async function capture(page: Page, origin: string, scenario:Scenario, name: string,credentials:VisualCredentials|null) {
  const {path}=scenario;
  const response = await page.goto(new URL(path, origin).toString(), { waitUntil: "networkidle" });
  await readVisualState(page,fixture.clock);
  const settledLegacyCharts=await settleLegacyCharts(page);
  if(scenario.authenticated) {
    if(response?.status()!==200)throw new Error(`Authenticated manage expected 200, received ${response?.status()}`);
    await page.getByRole("heading",{name:"Управление каналами",exact:true}).waitFor();
    if(scenario.state==="manage-matrix") {
      await page.locator("#matrixInstitution").selectOption("1");
      await page.locator(".platform-forms").evaluate((element)=>element.scrollIntoView({block:"start"}));
    } else if(scenario.state==="manage-edit-name") {
      await page.locator(".institution-cell details summary").first().click();
      await page.locator(".platform-table").evaluate((element)=>element.scrollIntoView({block:"start"}));
    }
  }
  const contentType = response?.headers()["content-type"] ?? "";
  const protocolJson = /application\/json/i.test(contentType);
  const responseBodySha256 = protocolJson && response ? createHash("sha256").update(await response.body()).digest("hex") : null;
  await page.evaluate(() => document.fonts.ready);
  await page.waitForFunction(() => [...document.querySelectorAll("canvas[data-chart-ready]")].every((canvas) => canvas.getAttribute("data-chart-ready") === "true"));
  if(scenario.chartIndex!==undefined) {
    if(scenario.state==="chart-light")await page.getByRole("button",{name:"Включить светлую тему"}).click();
    const canvas=page.locator("canvas").nth(scenario.chartIndex);
    await canvas.evaluate((element)=>element.scrollIntoView({block:"start"}));
    const bounds=await canvas.boundingBox();
    if(!bounds)throw new Error("Requested chart has no visible bounding box");
    if(scenario.state==="chart-hover")await page.mouse.move(bounds.x+bounds.width*.7,bounds.y+bounds.height*.4);
    else await page.mouse.move(1,1);
    await page.waitForTimeout(250); // Pointer/theme event rendering settles; canvas animation is disabled above.
  }
  const png = await page.screenshot({ type: "png", fullPage: false, animations: "disabled" });
  const decoded = PNG.sync.read(png);
  const viewport = page.viewportSize()!;
  if (decoded.width !== viewport.width || decoded.height !== viewport.height) throw new Error("Screenshot dimensions do not match viewport");
  await writeFile(resolve(directory, `${name}.png`), png);
  const secrets=await page.locator('input[name="csrf_token"],input[name="_csrf"],input[type="password"]').evaluateAll((elements)=>elements.map((element)=>(element as HTMLInputElement).value));
  if(credentials)secrets.push(credentials.password,Buffer.from(`${credentials.username}:${credentials.password}`).toString("base64"));
  const redact=(value:string)=>redactVisualEvidence(value,secrets);
  await writeFile(resolve(directory, `${name}.dom.html`), redact(await page.content()));
  await writeFile(resolve(directory, `${name}.aria.yml`), redact(await page.locator("body").ariaSnapshot()));
  const visualState=await readVisualState(page,fixture.clock);
  const measurements = {...await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    viewportWidth: window.innerWidth,
    styles: [...document.querySelectorAll("body,h1,h2,.site-header,.main-nav,.panel,th,input,button,.choice")].slice(0, 100).map((element) => {
      const css = getComputedStyle(element);
      return { selector: `${element.tagName}.${element.className}`, fontFamily: css.fontFamily, fontSize: css.fontSize, fontWeight: css.fontWeight,
        color: css.color, background: css.backgroundColor, padding: css.padding, margin: css.margin, border: css.border, boxShadow: css.boxShadow,
        position: css.position, overflow: css.overflow, width: css.width, height: css.height };
    }),
  })),cls:visualState.cls,visualState,settledLegacyCharts};
  await writeFile(resolve(directory, `${name}.computed.json`), redact(JSON.stringify(measurements, null, 2)));
  const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  await writeFile(resolve(directory, `${name}.axe.json`), redact(JSON.stringify(axe.violations, null, 2)));
  return { page,storageMasks:process.env.VISUAL_STORAGE_MASKS==="true"&&scenario.authenticated?await storageValues(page):[],png: decoded, status: response?.status(), sha256: createHash("sha256").update(png).digest("hex"), measurements,
    violations: axe.violations.length, applicableViolations: protocolJson ? 0 : axe.violations.length,
    a11yScope: protocolJson ? "JSON protocol response: browser-generated viewer is outside HTML author control; exact response bytes are checked" : "HTML document",
    protocolJson, responseBodySha256,overviewStatuses:await readOverviewStatuses(page) };
}

try {
  const workerCount = Math.max(1,Math.min(4,Number(process.env.VISUAL_WORKERS ?? 2)));
  await Promise.all(Array.from({length:workerCount},async(_,worker) => {
  for (const viewport of viewports) {
    async function createContext(origin:string,credentials:VisualCredentials|null) {
    const context = await browser.newContext({ viewport, timezoneId: "Europe/Moscow", locale: "ru-RU", deviceScaleFactor: 1, colorScheme: "dark", reducedMotion: "reduce",...(credentials?{httpCredentials:{...credentials,origin:new URL(origin).origin}}:{}) });
    await context.route("https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js", (route) => route.fulfill({ path:resolve("node_modules/chart.js/dist/chart.umd.js"),contentType:"application/javascript" }));
    await context.addInitScript(visualInitScript(fixture.clock));
    if(origin===legacy)await context.addInitScript(legacyChartStillInit);
    return context;
    }
    const contexts:BrowserContext[]=[];
    const pages=new Map<string,Page>();
    async function scenarioPage(side:"legacy"|"target",authenticated:boolean) {
      const key=`${side}:${authenticated}`;
      const found=pages.get(key);if(found)return found;
      const context=await createContext(side==="legacy"?legacy!:target!,authenticated?(side==="legacy"?legacyAdmin:targetAdmin):null);
      contexts.push(context);const page=await context.newPage();pages.set(key,page);return page;
    }
    for (const [index, scenario] of scenarios.entries()) {
      if(index % workerCount !== worker) continue;
      const {path,state,authenticated,chartIndex}=scenario;
      const prefix = `${String(index).padStart(3, "0")}-${viewport.name}`;
      try {
      const before = await capture(await scenarioPage("legacy",authenticated), legacy, scenario, `${prefix}-legacy`,authenticated?legacyAdmin:null);
      if (captureOnly) { results.push({ worker,path,state,authenticated,chartIndex, viewport, legacyStatus: before.status, legacySha256: before.sha256 }); continue; }
      const after = await capture(await scenarioPage("target",authenticated), target!, scenario, `${prefix}-target`,authenticated?targetAdmin:null);
      const rawPixelDiffRatio=pixelmatch(before.png.data,after.png.data,undefined,viewport.width,viewport.height,{threshold:0.1,includeAA:true})/(viewport.width*viewport.height);
      const {masks,skipped:maskSkipped}=pairedStorageMasks(before.storageMasks,after.storageMasks);
      if(masks.length){for(const [side,captureResult] of [["legacy",before],["target",after]] as const){const masked=await maskedStorageScreenshot(captureResult.page,masks);captureResult.png=PNG.sync.read(masked);await writeFile(resolve(directory,`${prefix}-${side}.comparison.png`),masked);}}
      const diff = new PNG({ width: viewport.width, height: viewport.height });
      const changedPixels = pixelmatch(before.png.data, after.png.data, diff.data, viewport.width, viewport.height, { threshold: 0.1, includeAA: true });
      const ratio = changedPixels / (viewport.width * viewport.height);
      await writeFile(resolve(directory, `${prefix}-diff.png`), PNG.sync.write(diff));
      const protocolParity = before.protocolJson === after.protocolJson && (!before.protocolJson || before.responseBodySha256 === after.responseBodySha256);
      const overviewStatusParity=compareOverviewStatuses(before.overviewStatuses,after.overviewStatuses,true);
      const passed = ratio <= 0.005 && before.status === after.status && protocolParity && overviewStatusParity.passed && after.applicableViolations === 0 && after.measurements.cls <= 0.1 && after.measurements.scrollWidth <= viewport.width;
      if (!passed) failed = true;
      results.push({ worker,path,state,authenticated,chartIndex, viewport, legacyStatus: before.status, targetStatus: after.status, legacySha256: before.sha256, targetSha256: after.sha256,
        changedPixels, pixelDiffRatio: ratio,rawPixelDiffRatio, threshold: 0.005, masks,maskSkipped, targetAxeViolations: after.violations,
        applicableAxeViolations: after.applicableViolations,a11yScope: after.a11yScope,protocolParity,overviewStatusParity,
        targetCls: after.measurements.cls,legacyCls:before.measurements.cls,legacyInstrumentation:before.measurements.visualState,targetInstrumentation:after.measurements.visualState,settledLegacyCharts:before.measurements.settledLegacyCharts,targetScrollWidth:after.measurements.scrollWidth,passed });
      console.log(`${prefix} ${path} [${state}]: ${(ratio * 100).toFixed(4)}% pixels, axe=${after.violations}, ${passed ? "PASS" : "FAIL"}`);
      } catch(error) {
        failed = true;
        results.push({worker,path,state,authenticated,chartIndex,viewport,passed:false,error:error instanceof Error ? error.message : String(error)});
        console.log(`${prefix} ${path}: CAPTURE FAILED`);
      }
      await writeFile(resolve(directory,`progress-${worker}.json`),JSON.stringify({worker,scope:"worker",fixture,results:results.filter((row) => row.worker===worker)},null,2));
    }
    await Promise.all(contexts.map((context)=>context.close()));
  }
  }));
} finally { await browser.close(); }
const revisionAfter=await readRevision();
const coherent=JSON.stringify(revisionBefore)===JSON.stringify(revisionAfter);
if(!coherent)failed=true;
await writeFile(resolve(directory, "report.json"), JSON.stringify({ generatedAt: new Date().toISOString(), producerFilesSha256, legacyOrigin:legacy,targetOrigin:target, fixture,sourceSha256,buildId,runtimeEvidencePath,runtimeEvidence,revisionBefore,revisionAfter,coherent, browser: "Playwright pinned Chromium", instrumentation: { version: 3, frozenClockRequired: true, cls: "Maximum 5s session with gaps below 1s; registered observer required, no missing-value fallback", chartStills: "A legacy-only init hook sets Chart.defaults.animation=false when the original library is assigned to window.Chart, before any chart construction; a post-navigation stop confirms the final endpoint. Library bytes, data, scales, tooltip formatting and natural pointer selection are unchanged. Performance runs do not install this hook or freeze time." }, captureOnly,fullScope,authenticatedManageCoverage:authenticatedReady?"INCLUDED":"NOT_RUN_MISSING_CREDENTIALS",secretHandling:"Administrator credentials stay in per-origin browser authentication contexts. CSRF/password values are redacted from text artifacts; raw screenshots have no masks. Explicit VISUAL_STORAGE_MASKS may create separate comparison screenshots for only paired live storage values; every rectangle is reported.", gate: captureOnly ? "BASELINE_ONLY" : failed ? "NO-GO" : "PASS", results }, null, 2) + "\n");
console.log(directory);
if (failed) process.exitCode = 1;
