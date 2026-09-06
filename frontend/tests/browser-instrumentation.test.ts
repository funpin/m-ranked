import test from "node:test";
import assert from "node:assert/strict";
import { createContext,runInContext } from "node:vm";
import type { Page } from "@playwright/test";
import { visualInitScript,readVisualState,mobileObserverInit,readMobileMetrics,legacyChartStillInit } from "../scripts/browser-instrumentation.mjs";

const clock="2026-08-01T12:00:00Z";
function browserRealm(supported=["layout-shift","event","largest-contentful-paint"]) {
  const callbacks=new Map<string,(list:{getEntries:()=>unknown[]})=>void>();
  const context=createContext({localStorage:{setItem(){}},PerformanceObserver:class {
    static supportedEntryTypes=supported;
    constructor(readonly callback:(list:{getEntries:()=>unknown[]})=>void){}
    observe({type}:{type:string}){callbacks.set(type,this.callback);}
  }});
  runInContext("window=globalThis",context);
  const page={evaluate:(expression:string)=>Promise.resolve(runInContext(expression,context))} as unknown as Page;
  return {context,page,callbacks};
}

test("visual initializer runs without any transpiler globals and preserves Date construction",async()=>{
  const {context,page,callbacks}=browserRealm();
  assert.equal(runInContext("typeof __name",context),"undefined");
  runInContext(visualInitScript(clock).content,context);
  const state=await readVisualState(page,clock);
  assert.equal(state.cls,0);assert.equal(callbacks.size,1);
  assert.equal(runInContext("new Date().toISOString()",context),"2026-08-01T12:00:00.000Z");
  assert.equal(runInContext("new Date(2000,0,1).getFullYear()",context),2000);
  assert.equal(runInContext("Date.parse('2000-01-01T00:00:00Z')",context),946684800000);
  assert.equal(runInContext("Date.UTC(2000,0,1)",context),946684800000);
  assert.equal(runInContext("new Date() instanceof Date",context),true);
  assert.match(runInContext("Date()",context),/2026/);
});

test("visual CLS is observed and uses the maximum session instead of a missing-value zero",async()=>{
  const {context,page,callbacks}=browserRealm();runInContext(visualInitScript(clock).content,context);
  callbacks.get("layout-shift")!({getEntries:()=>[
    {startTime:1000,value:.2,hadRecentInput:false},{startTime:1500,value:.2,hadRecentInput:false},
    {startTime:2000,value:99,hadRecentInput:true},{startTime:7000,value:.3,hadRecentInput:false},
  ]});
  assert.equal((await readVisualState(page,clock)).cls,.4);
  runInContext("delete window.__visualCapture",context);
  await assert.rejects(readVisualState(page,clock),/did not initialize/);
});

test("unsupported or altered visual instrumentation fails closed",async()=>{
  const unsupported=browserRealm([]);
  assert.throws(()=>runInContext(visualInitScript(clock).content,unsupported.context),/unavailable/);
  await assert.rejects(readVisualState(unsupported.page,clock),/did not initialize/);
  const {context,page}=browserRealm();runInContext(visualInitScript(clock).content,context);
  runInContext("window.Date={now:()=>42}",context);
  await assert.rejects(readVisualState(page,clock),/was not frozen/);
});

test("mobile observers all register without freezing time or depending on a TSX helper",async()=>{
  const {context,page,callbacks}=browserRealm();const before=Date.now();
  runInContext(mobileObserverInit.content,context);
  assert.deepEqual([...callbacks.keys()].sort(),["event","largest-contentful-paint","layout-shift"]);
  assert.ok(runInContext("Date.now()",context)>=before);
  callbacks.get("largest-contentful-paint")!({getEntries:()=>[{startTime:1250}]});
  callbacks.get("event")!({getEntries:()=>[{interactionId:12,duration:48},{interactionId:12,duration:80}]});
  const metrics=await readMobileMetrics(page);assert.equal(metrics.lcp,1250);assert.equal(metrics.interactions["12"],80);
  runInContext("window.__mobileLab.initialized=false",context);
  await assert.rejects(readMobileMetrics(page),/did not initialize/);
});

 test("legacy static-capture animation is disabled before the first original chart constructor",()=>{
  const {context}=browserRealm();
  runInContext(legacyChartStillInit.content,context);
  runInContext("window.originalChart = function Chart() { if (Chart.defaults.animation !== false) throw new Error('animated'); }; originalChart.defaults={animation:{duration:1000}}; window.Chart=originalChart; new Chart();",context);
  assert.equal(runInContext("Chart === originalChart",context),true);
  assert.equal(runInContext("window.__legacyChartStill.configured",context),true);
  assert.equal(runInContext("window.__legacyChartStill.assignments",context),1);
});
