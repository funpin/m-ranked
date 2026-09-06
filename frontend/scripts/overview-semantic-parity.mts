import { chromium } from "@playwright/test";
import { createHash } from "node:crypto";
import { mkdir,readFile,writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import assert from "node:assert/strict";
import { readOverviewStatuses,compareOverviewStatuses,canonicalOverviewStatuses,type OverviewStatus } from "./overview-semantics.mjs";

const legacy=process.env.LEGACY_BASE_URL,target=process.env.TARGET_BASE_URL,
  manifestPath=process.env.VISUAL_FIXTURE_MANIFEST,runtimePath=process.env.VISUAL_RUNTIME_EVIDENCE,dist=process.env.NEXT_DIST_DIR;
if(!legacy||!target||!manifestPath||!runtimePath||!dist)throw new Error("Both origins, frozen fixture, runtime evidence and NEXT_DIST_DIR are required");
const fixture=JSON.parse(await readFile(manifestPath,"utf8")),runtime=JSON.parse(await readFile(runtimePath,"utf8"));
const sha=(value:Buffer|string)=>createHash("sha256").update(value).digest("hex");
const sourceSha256=sha(await readFile(fixture.path));
assert.equal(sourceSha256,fixture.sha256);assert.equal(sourceSha256,runtime.sourceSha256);
const revision=async()=>{const response=await fetch(new URL("/api/v1/revision",runtime.apiBaseUrl),{cache:"no-store",signal:AbortSignal.timeout(8000)});assert.equal(response.status,200);return response.json();};
const revisionBefore=await revision();
assert.equal(revisionBefore.datasetRevision,runtime.database.datasetRevision);
assert.equal(revisionBefore.representationVersion,runtime.revision.representationVersion);
const buildId=(await readFile(resolve(dist,"BUILD_ID"),"utf8")).trim();
const output=resolve(process.env.SEMANTIC_OUTPUT??"evidence/overview-semantic-parity");await mkdir(output,{recursive:true});
const browser=await chromium.launch(),results=[];
try {
  const context=await browser.newContext({locale:"ru-RU",timezoneId:"Europe/Moscow",viewport:{width:1440,height:900}});
  const before=await context.newPage(),after=await context.newPage();
  const destinations=new Map<string,string>();
  const resolveHref=async(href:string)=>{
    if(destinations.has(href))return destinations.get(href)!;
    const original=new URL(href,target);
    assert.equal(original.origin,new URL(target).origin);
    const response=await context.request.get(original.toString());
    assert.equal(response.status(),200,`Legacy card destination must still resolve: ${href}`);
    const destination=new URL(response.url());
    assert.equal(destination.origin,original.origin,"Compatibility redirect must stay on the target origin");
    const canonical=destination.pathname+destination.search;
    destinations.set(href,canonical);
    await response.dispose();
    return canonical;
  };
  for(const platform of ["telegram","vk","max","rutube","all"])for(const period of ["3h","1d","7d","30d"]) {
    const route=`/?platform=${platform}&period=${period}`;
    assert.equal((await before.goto(new URL(route,legacy).toString(),{waitUntil:"networkidle"}))?.status(),200);
    const legacyStatuses=await readOverviewStatuses(before);
    const expected=await canonicalOverviewStatuses(legacyStatuses,resolveHref),actual:OverviewStatus[]=[],pages:string[]=[];
    let next:string|null=new URL(route,target).toString();
    while(next) {
      assert.ok(pages.length<100&&!pages.includes(next),"Continuation must terminate without repeated pages");
      assert.equal(new URL(next).origin,new URL(target).origin);
      pages.push(next);
      assert.equal((await after.goto(next,{waitUntil:"networkidle"}))?.status(),200);
      const items=await readOverviewStatuses(after);
      assert.ok(items.length>0,"Representative overview cannot silently become empty or an error page");
      actual.push(...items);
      const link=after.getByRole("link",{name:"Следующая страница",exact:true});
      const href=await link.count()?await link.getAttribute("href"):null;
      next=href?new URL(href,target).toString():null;
    }
    const result={route,pages,...compareOverviewStatuses(expected,actual),legacySha256:sha(JSON.stringify(legacyStatuses)),targetSha256:sha(JSON.stringify(actual)),legacyStatuses,expected,actual};
    results.push(result);
    await writeFile(resolve(output,"progress.json"),JSON.stringify(results,null,2)+"\n");
    console.log(`${route}: ${actual.length}/${expected.length} cards, ${pages.length} pages, ${result.passed?"PASS":"FAIL"}`);
  }
} finally {await browser.close();}
const revisionAfter=await revision(),coherent=JSON.stringify(revisionBefore)===JSON.stringify(revisionAfter);
const gate=coherent&&results.length===20&&results.every((row)=>row.passed)?"PASS":"NO-GO";
await writeFile(resolve(output,"report.json"),JSON.stringify({generatedAt:new Date().toISOString(),scope:"Exact rendered status text, CSS state, title and canonical destination resolved from each legacy href of every overview card, including all continuation pages, for 5 platforms and 4 periods. Whitespace alone is normalized. No pixel tolerance applies.",legacyOrigin:legacy,targetOrigin:target,sourceSha256,fixture,runtimePath,runtime,buildId,revisionBefore,revisionAfter,coherent,gate,results},null,2)+"\n");
if(gate!=="PASS")process.exitCode=1;
