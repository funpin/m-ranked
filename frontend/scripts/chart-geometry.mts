import {chromium} from "@playwright/test";
import {mkdir,writeFile,readFile} from "node:fs/promises";
import {resolve} from "node:path";

const origin=process.env.LEGACY_BASE_URL;
if(!origin||!process.env.VISUAL_FIXTURE_MANIFEST)throw new Error("Explicit frozen legacy origin/manifest required");
const fixture=JSON.parse(await readFile(process.env.VISUAL_FIXTURE_MANIFEST,"utf8"));
const directory=resolve(process.env.CHART_GEOMETRY_OUTPUT??"evidence/legacy-chart-geometry-r1");
await mkdir(directory,{recursive:true});
const browser=await chromium.launch();
const rows=[];
try{for(const viewport of [{width:1440,height:900},{width:390,height:844}])for(const path of process.env.CHART_GEOMETRY_ROUTES?JSON.parse(process.env.CHART_GEOMETRY_ROUTES) as string[]:["/compare?platform=vk&submitted=true&institutions=1&institutions=3&period=168","/compare?platform=vk","/posts/1","/platform-posts/1"]) {
  const context=await browser.newContext({viewport,deviceScaleFactor:1,locale:"ru-RU",timezoneId:"Europe/Moscow"});
  await context.route("https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js",(route)=>route.fulfill({path:resolve("node_modules/chart.js/dist/chart.umd.js"),contentType:"application/javascript"}));
  const page=await context.newPage();await page.goto(new URL(path,origin).href,{waitUntil:"networkidle"});
  if(process.env.CHART_GEOMETRY_THEME==="light"){await page.getByRole("button",{name:"Включить светлую тему"}).click();await page.waitForTimeout(Number(process.env.CHART_GEOMETRY_THEME_WAIT_MS??250));}
  const geometry=await page.evaluate(()=>{
    // Diagnostic access to the pinned legacy renderer; never shipped to visitors.
    const charts=(window as unknown as {Chart:{instances:Record<string,{
      width:number;height:number;chartArea:unknown;options:unknown;
      scales:Record<string,{left:number;top:number;width:number;height:number;min:number;max:number;ticks:unknown[];options:{ticks:{color:string};grid:{color:string};title:{color:string}}}>;
      data:{datasets:unknown[]};
      getDatasetMeta:(index:number)=>{data:{options:Record<string,unknown>}[]};
    }>}}).Chart.instances;
    return Object.values(charts).map((chart)=>({width:chart.width,height:chart.height,chartArea:chart.chartArea,seriesCount:chart.data.datasets.length,firstPointStyles:chart.data.datasets.map((_,index)=>{const options=chart.getDatasetMeta(index).data[0]?.options;return options?Object.fromEntries(["radius","borderWidth","borderColor","backgroundColor","hitRadius"].map((key)=>[key,options[key]])):null;}),
      scales:Object.fromEntries(Object.entries(chart.scales).map(([key,scale])=>[key,{left:scale.left,top:scale.top,width:scale.width,height:scale.height,min:scale.min,max:scale.max,colors:{ticks:scale.options.ticks.color,grid:scale.options.grid.color,title:scale.options.title.color},ticks:scale.ticks.map((tick)=>{const {value,label}=tick as {value:number;label:string};return {value,label};})}]))}));
  });
  rows.push({path,viewport,geometry});
  for(const [index,canvas] of (await page.locator("canvas").all()).entries()){await canvas.scrollIntoViewIfNeeded();await canvas.screenshot({path:resolve(directory,`${rows.length}-${index}-plot.png`)});}
  await context.close();
}}finally{await browser.close();}
await writeFile(resolve(directory,"report.json"),JSON.stringify({fixture,scope:"Diagnostic plot geometry and unmasked canvas captures, not a full viewport release gate",rows},null,2));
