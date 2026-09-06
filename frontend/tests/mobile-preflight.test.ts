import test from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { createHash } from "node:crypto";
import { mkdtemp,writeFile,rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join,resolve } from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execute=promisify(execFile);

test("mobile producer rejects unrelated runtime evidence before starting a browser or reading an artifact",async(t)=>{
  const directory=await mkdtemp(join(tmpdir(),"mranked-mobile-preflight-"));
  const revision={datasetRevision:30,representationVersion:"a".repeat(64),asOf:"2026-08-01T12:00:00Z"};
  const server=createServer((_request,response)=>{response.setHeader("Content-Type","application/json");response.end(JSON.stringify(revision));});
  await new Promise<void>((resolve)=>server.listen(0,"127.0.0.1",resolve));
  const address=server.address();assert.ok(address&&typeof address!=="string");
  const origin=`http://127.0.0.1:${address.port}`;
  try {
    const source=join(directory,"frozen-source"),manifest=join(directory,"manifest.json"),runtimeFile=join(directory,"runtime.json");
    const bytes=Buffer.from("isolated producer validation source"),sourceSha256=createHash("sha256").update(bytes).digest("hex");
    await writeFile(source,bytes);
    await writeFile(manifest,JSON.stringify({path:source,sha256:sourceSha256,counts:{institutions:207,platform_accounts:824,posts:206,platform_posts:618,reaction_snapshots:2258,platform_snapshots:6768}}));
    const runtime={sourceSha256,apiBaseUrl:origin,database:{datasetRevision:30,institutions:207,accounts:824,publications:824,snapshots:9026,comparisonPoints:8_534_560},revision};
    const cases=[
      {name:"different source",runtime:{...runtime,sourceSha256:"0".repeat(64)},message:"Runtime and frozen source must match"},
      {name:"different API origin",runtime:{...runtime,apiBaseUrl:"http://127.0.0.1:1"},message:"Runtime evidence must identify the measured API origin"},
      {name:"stale dataset",runtime:{...runtime,database:{...runtime.database,datasetRevision:29}},message:"Dataset changed since runtime evidence was recorded"},
      {name:"stale representation",runtime:{...runtime,revision:{...revision,representationVersion:"b".repeat(64)}},message:"API representation changed since runtime evidence was recorded"},
    ];
    for(const example of cases)await t.test(example.name,async()=>{
      await writeFile(runtimeFile,JSON.stringify(example.runtime));
      await assert.rejects(execute(process.execPath,["--import","tsx","scripts/mobile-performance.mts"],{
        cwd:resolve(import.meta.dirname,".."),timeout:15_000,
        env:{...process.env,API_BASE_URL:origin,PERFORMANCE_BASE_URL:"http://127.0.0.1:1",VISUAL_FIXTURE_MANIFEST:manifest,PERFORMANCE_RUNTIME_EVIDENCE:runtimeFile,NEXT_DIST_DIR:join(directory,"deliberately-absent-artifact")},
      }),(error:unknown)=>{
        const failure=error as {code?:number;stderr?:string};
        assert.equal(failure.code,1);
        assert.ok(failure.stderr?.includes(example.message),failure.stderr);
        assert.ok(!failure.stderr?.includes("ENOENT"),"A rejected preflight must not read the artifact");
        return true;
      });
    });
  } finally {
    await new Promise<void>((resolve,reject)=>server.close((error)=>error?reject(error):resolve()));
    await rm(directory,{recursive:true,force:true});
  }
});
