import { chromium } from "@playwright/test";
import { resolve } from "node:path";
const clock="2026-08-01T12:00:00+00:00";
const init=({clock}:{clock:string})=>{
  try{localStorage.setItem("m-ranked-theme","dark");}catch{}
  const now=Date.parse(clock),OriginalDate=Date;
  class FrozenDate extends OriginalDate {constructor(...args:[]|[string|number]){super(args.length?args[0]!:now);}static now(){return now;}}
  window.Date=FrozenDate as DateConstructor;
  (window as unknown as {visualCls:number}).visualCls=0;
  new PerformanceObserver((entries)=>entries.getEntries().forEach((entry)=>{
    const shift=entry as PerformanceEntry&{value:number;hadRecentInput:boolean};
    if(!shift.hadRecentInput)(window as unknown as {visualCls:number}).visualCls+=shift.value;
  })).observe({type:"layout-shift",buffered:true});
};
const browser=await chromium.launch();
try{
  const context=await browser.newContext({viewport:{width:1440,height:900},locale:"ru-RU",timezoneId:"Europe/Moscow"});
  await context.route("https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js",route=>route.fulfill({path:resolve("node_modules/chart.js/dist/chart.umd.js"),contentType:"application/javascript"}));
  await context.addInitScript(init,{clock});
  const page=await context.newPage(),errors:string[]=[];
  page.on("pageerror",error=>errors.push(error.message));
  await page.goto("http://127.0.0.1:18088/platform-posts/1",{waitUntil:"networkidle"});
  await page.evaluate(()=>document.fonts.ready);
  const initial=await page.evaluate(()=>({now:Date.now(),cls:(window as unknown as {visualCls?:number}).visualCls??null}));
  await page.evaluate(()=>Object.values((window as unknown as {Chart:{instances:Record<string,{stop:()=>void;update:(mode:string)=>void}>}}).Chart.instances).forEach(chart=>{chart.stop();chart.update("none");}));
  const canvas=page.locator("canvas").first();await canvas.evaluate(element=>element.scrollIntoView({block:"start"}));
  const bounds=(await canvas.boundingBox())!;
  const point=await page.evaluate(()=>{
    const chart=Object.values((window as unknown as {Chart:{instances:Record<string,{data:{datasets:{data:(number|null)[]}[]};getDatasetMeta:(index:number)=>{data:{x:number;y:number;base:number}[]}}>}}).Chart.instances)[0]!;
    const index=chart.data.datasets[0]!.data.findIndex(value=>value!==null);
    const element=chart.getDatasetMeta(0).data[index]!;
    return {index,x:element.x,y:element.y,base:element.base};
  });
  console.log(JSON.stringify({initContainsNamingHelper:init.toString().includes("__name"),expectedNow:Date.parse(clock),initial,errors,point},null,2));
  await page.mouse.move(bounds.x+point.x,bounds.y+point.y+(Number.isFinite(point.base)?(point.base-point.y)*.5:0));
  await page.waitForTimeout(500);
  const tooltip=await page.evaluate(()=>{
    const chart=Object.values((window as unknown as {Chart:{instances:Record<string,{tooltip:{opacity:number;title:string[];body:{lines:string[]}[]};options:{animation:unknown}} >}}).Chart.instances)[0]!;
    return {opacity:chart.tooltip.opacity,title:chart.tooltip.title,body:chart.tooltip.body};
  });
  console.log(JSON.stringify({initContainsNamingHelper:init.toString().includes("__name"),expectedNow:Date.parse(clock),initial,errors,tooltip},null,2));
}finally{await browser.close();}
