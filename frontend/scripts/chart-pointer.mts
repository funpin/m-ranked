import {chromium} from "@playwright/test";
import {writeFile,mkdir} from "node:fs/promises";
import {resolve} from "node:path";
const browser=await chromium.launch(),rows=[];
try{for(const origin of [process.env.LEGACY_BASE_URL,process.env.TARGET_BASE_URL]){
  if(!origin)throw new Error("Both explicit local origins are required");
  const context=await browser.newContext({viewport:{width:390,height:844},locale:"ru-RU",timezoneId:"Europe/Moscow"});
  await context.route("https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js",route=>route.fulfill({path:resolve("node_modules/chart.js/dist/chart.umd.js"),contentType:"application/javascript"}));
  const page=await context.newPage();await page.goto(new URL("/compare?platform=vk",origin).href,{waitUntil:"networkidle"});
  await page.waitForFunction(()=>[...document.querySelectorAll("canvas[data-chart-ready]")].every(c=>c.getAttribute("data-chart-ready")==="true"));
  for(const chartIndex of [0,1]){
    const canvas=page.locator("canvas").nth(chartIndex);await canvas.evaluate(element=>{
      const result={events:[] as unknown[],texts:[] as unknown[]};Object.assign(window,{__pointerProbe:result});
      element.addEventListener("mousemove",event=>{const e=event as MouseEvent;result.events.push({clientX:e.clientX,clientY:e.clientY,offsetX:e.offsetX,offsetY:e.offsetY,rect:element.getBoundingClientRect().toJSON()});});
      const draw=CanvasRenderingContext2D.prototype.fillText;CanvasRenderingContext2D.prototype.fillText=function(text,x,y,...rest){if(/ВУЗ|Через|Выборка/.test(text))result.texts.push({text,x,y});return draw.call(this,text,x,y,...rest);};
      element.scrollIntoView({block:"start"});
    });
    const box=(await canvas.boundingBox())!;await page.mouse.move(1,1);await page.mouse.move(box.x+box.width*.7,box.y+box.height*.4);await page.waitForTimeout(300);
    rows.push({origin,chartIndex,probe:await page.evaluate((index)=>{
      const global=window as unknown as {__pointerProbe:unknown;Chart?:{instances:Record<string,{scales:Record<string,{min:number;max:number;top:number;bottom:number;left:number;right:number}>;tooltip:{x:number;y:number;caretX:number;caretY:number;dataPoints:{parsed:unknown;datasetIndex:number;dataIndex:number}[]};_lastEvent:{x:number;y:number;type:string}}>}};
      const chart=Object.values(global.Chart?.instances??{})[index];return {events:global.__pointerProbe,legacy:chart?{scales:Object.fromEntries(Object.entries(chart.scales).map(([id,s])=>[id,{min:s.min,max:s.max,top:s.top,bottom:s.bottom,left:s.left,right:s.right}])),tooltip:{x:chart.tooltip.x,y:chart.tooltip.y,caretX:chart.tooltip.caretX,caretY:chart.tooltip.caretY,points:chart.tooltip.dataPoints.map(p=>({parsed:p.parsed,datasetIndex:p.datasetIndex,dataIndex:p.dataIndex}))},event:{x:chart._lastEvent?.x,y:chart._lastEvent?.y,type:chart._lastEvent?.type}}:null};
    },chartIndex)});
  }await context.close();
}}finally{await browser.close();}
const output=process.env.CHART_POINTER_OUTPUT??"evidence/chart-pointer-r1";await mkdir(output,{recursive:true});await writeFile(resolve(output,"report.json"),JSON.stringify(rows,null,2));
