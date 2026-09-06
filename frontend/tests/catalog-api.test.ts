import assert from "node:assert/strict";
import test from "node:test";
import {catalogReader,CatalogApiError} from "../lib/catalog-api";

test("private catalog reader forwards only session headers and never caches",async()=>{
  const reader=catalogReader(new Headers({authorization:"Basic test-session",cookie:"XSRF-TOKEN=csrf",host:"untrusted.example","x-injected":"do not forward"}),async(input,init)=>{
    const url=new URL(String(input));assert.equal(url.origin,"https://api.test");assert.equal(init?.cache,"no-store");assert.equal(init?.redirect,"error");
    const headers=new Headers(init?.headers);assert.equal(headers.get("authorization"),"Basic test-session");assert.equal(headers.get("cookie"),"XSRF-TOKEN=csrf");assert.equal(headers.get("host"),null);assert.equal(headers.get("x-injected"),null);
    return Response.json({items:[],nextAfter:null});
  },"https://api.test");
  assert.deepEqual(await reader.institutions(),[]);
});
test("catalog and nested account continuation retain all rows beyond first page",async()=>{
  const account=(id:number)=>({id:`account-${id}`,institutionId:"institution-1",legacyId:id,rowVersion:0});
  const institution=(id:number)=>({id:`institution-${id}`,legacyId:id,name:`Institution ${id}`,rowVersion:0,accounts:id===1?[account(1)]:[],nextAccountAfter:id===1?1:null});
  const requests:string[]=[];
  const reader=catalogReader(new Headers(),async(input)=>{
    const url=new URL(String(input));requests.push(url.pathname+url.search);
    if(url.pathname.endsWith("/accounts")) return Response.json({items:Array.from({length:60},(_,i)=>account(i+2)),nextAfter:null});
    return Response.json(url.searchParams.get("after")==="0"?{items:Array.from({length:200},(_,i)=>institution(i+1)),nextAfter:200}:{items:[institution(201)],nextAfter:null});
  },"https://api.test");
  const rows=await reader.institutions();assert.equal(rows.length,201);assert.equal(rows[0]!.accounts.length,61);assert.equal(requests.length,3);
});
test("stale or malformed catalog cursors fail explicitly",async()=>{
  const reader=catalogReader(new Headers(),async()=>Response.json({items:[],nextAfter:0}),"https://api.test");
  await assert.rejects(()=>reader.institutions(),(error:unknown)=>error instanceof CatalogApiError&&error.status===502);
});
test("authorization failures do not expose upstream response bodies",async()=>{
  const reader=catalogReader(new Headers(),async()=>new Response("sensitive upstream detail",{status:403}),"https://api.test");
  await assert.rejects(()=>reader.institutions(),(error:unknown)=>error instanceof CatalogApiError&&error.status===403&&!error.message.includes("sensitive"));
});
