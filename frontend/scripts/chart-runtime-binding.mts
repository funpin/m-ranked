import {readFile,readdir,mkdir,writeFile} from "node:fs/promises";
import {resolve,relative} from "node:path";
import {createHash} from "node:crypto";
import assert from "node:assert/strict";
import {createApiClient} from "../lib/api.js";
import {collectPages} from "../lib/continuation.js";

const runtimePath=process.env.BINDING_RUNTIME_EVIDENCE,dist=process.env.NEXT_DIST_DIR,manifestPath=process.env.VISUAL_FIXTURE_MANIFEST;
if(!runtimePath||!dist||!manifestPath)throw new Error("BINDING_RUNTIME_EVIDENCE, NEXT_DIST_DIR and VISUAL_FIXTURE_MANIFEST are required");
const runtime=JSON.parse(await readFile(runtimePath,"utf8")),fixture=JSON.parse(await readFile(manifestPath,"utf8"));
const hash=(value:string|Buffer)=>createHash("sha256").update(value).digest("hex");
const canonical=(value:unknown):string=>JSON.stringify(value===null||typeof value!=="object"?value:Array.isArray(value)?value.map((item)=>JSON.parse(canonical(item))):Object.fromEntries(Object.keys(value).sort().map((key)=>[key,JSON.parse(canonical((value as Record<string,unknown>)[key]))])));
const sourceSha256=hash(await readFile(fixture.path));
assert.equal(sourceSha256,fixture.sha256);assert.equal(sourceSha256,runtime.sourceSha256);
const revision=async()=>{const response=await fetch(new URL("/api/v1/revision",runtime.apiBaseUrl),{cache:"no-store",signal:AbortSignal.timeout(8000)});assert.equal(response.status,200);return response.json();};
const revisionBefore=await revision();
assert.equal(revisionBefore.datasetRevision,runtime.database.datasetRevision);
assert.equal(revisionBefore.representationVersion,runtime.revision.representationVersion);
const buildId=(await readFile(resolve(dist,"BUILD_ID"),"utf8")).trim();
const artifactRoot=resolve(dist);
const files:{path:string;sha256:string;bytes:number}[]=[];
async function artifactFiles(directory:string){for(const entry of await readdir(directory,{withFileTypes:true})){const path=resolve(directory,entry.name);if(entry.isDirectory())await artifactFiles(path);else if(entry.isFile()){const bytes=await readFile(path);files.push({path:relative(artifactRoot,path),sha256:hash(bytes),bytes:bytes.length});}}}
await artifactFiles(resolve(dist,"server"));await artifactFiles(resolve(dist,"static"));
files.sort((a,b)=>a.path.localeCompare(b.path));
const artifactSha256=hash(canonical(files));
const requests=new Map<string,{path:string;status:number;bytes:number;rawSha256:string;canonicalSha256:string}>();
const client=createApiClient({baseUrl:runtime.apiBaseUrl,cacheEntries:0,timeoutMs:30_000,fetcher:async(input,init)=>{
  const response=await fetch(input,init),body=await response.clone().text(),url=new URL(input instanceof Request?input.url:input),path=url.pathname+url.search;
  assert.equal(response.status,200,`Actual chart input ${url.pathname} must be available`);
  const item={path,status:response.status,bytes:Buffer.byteLength(body),rawSha256:hash(body),canonicalSha256:hash(canonical(JSON.parse(body)))};
  const prior=requests.get(path);if(prior)assert.equal(item.canonicalSha256,prior.canonicalSha256,"A repeated input changed inside one capture");requests.set(path,item);return response;
}});
const scenarios:string[]=[];
for(const platform of ["telegram","vk","rutube"] as const){
  await collectPages((cursor)=>client.comparisonCandidates(platform,200,cursor),(page)=>page.nextCursor);
  await collectPages((selectionCursor)=>client.comparison({platform,horizonHours:72,includePartial:false,metric:"reactions",aggregation:"median",institutionLimit:50,selectionCursor}),(page)=>page.nextSelectionCursor);
  scenarios.push(`/compare?platform=${platform}`);
}
for(const [institutions,horizonHours] of [[[1,2],72],[[1,3],168]] as const){
  await collectPages((selectionCursor)=>client.comparison({platform:"vk",institutions,horizonHours,includePartial:false,metric:"reactions",aggregation:"median",institutionLimit:50,selectionCursor}),(page)=>page.nextSelectionCursor);
  scenarios.push(`/compare?platform=vk&submitted=true&institutions=${institutions[0]}&institutions=${institutions[1]}&period=${horizonHours}`);
}
for(const type of ["posts","platform_posts"] as const){
  await client.publication(1,type);
  const pages=await collectPages((cursor)=>client.publicationHistory(1,type,100,cursor),(page)=>page.nextCursor),first=pages[0]!,publication=first.publication;
  if(publication.accountLegacyId&&publication.accountLegacyType)await client.account(publication.accountLegacyId,publication.accountLegacyType);
  for(const id of [first.previousLegacyId,first.nextLegacyId])if(id)await client.publication(id,type);
  scenarios.push(type==="posts"?"/posts/1":"/platform-posts/1");
}
const revisionAfter=await revision(),coherent=canonical(revisionBefore)===canonical(revisionAfter);
const inputs=[...requests.values()].sort((a,b)=>a.path.localeCompare(b.path));
const baselinePath=process.env.BINDING_BASELINE;
const baseline=baselinePath?JSON.parse(await readFile(baselinePath,"utf8")):null;
const sameRevision=!baseline||canonical(baseline.revisionBefore)===canonical(revisionBefore);
const sameArtifact=!baseline||baseline.buildId===buildId&&baseline.artifactSha256===artifactSha256;
const sameSource=!baseline||baseline.sourceSha256===sourceSha256;
const sameInputs=!baseline||canonical(baseline.inputs.map((item:{path:string;canonicalSha256:string})=>({path:item.path,canonicalSha256:item.canonicalSha256})))===canonical(inputs.map(({path,canonicalSha256})=>({path,canonicalSha256})));
const report={generatedAt:new Date().toISOString(),scope:"Read-only binding of the complete chart API inputs and unchanged server/static frontend artifact across server deployments. This is not a new screenshot capture, a performance measurement or production acceptance. Object keys are sorted for semantic JSON hashes; arrays, values, nulls and Unicode are preserved. Raw body hashes are also retained.",baselinePath:baselinePath??null,runtimeEvidencePath:runtimePath,apiOrigin:runtime.apiBaseUrl,jarSha256:runtime.jarSha256,sourceSha256,buildId,artifactSha256,files,scenarios,inputs,revisionBefore,revisionAfter,coherent,sameRevision,sameArtifact,sameSource,sameInputs,gate:coherent&&sameRevision&&sameArtifact&&sameSource&&sameInputs?baseline?"PASS":"BASELINE_ONLY":"NO-GO"};
const output=resolve(process.env.BINDING_OUTPUT??"evidence/chart-runtime-binding");await mkdir(output,{recursive:true});await writeFile(resolve(output,"report.json"),JSON.stringify(report,null,2)+"\n");
console.log(JSON.stringify({gate:report.gate,inputs:inputs.length,files:files.length,buildId,revision:revisionBefore.datasetRevision,sameInputs},null,2));
if(report.gate==="NO-GO")process.exitCode=1;
