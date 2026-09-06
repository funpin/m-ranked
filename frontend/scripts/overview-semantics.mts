import type { Page } from "@playwright/test";

export type OverviewStatus = { title:string; href:string|null; text:string; kind:string };

// Read user-visible state independently from the API and its rendering helper.
export async function readOverviewStatuses(page:Page):Promise<OverviewStatus[]> {
  return page.locator(".overview-grid .overview-card").evaluateAll((cards)=>cards.map((card)=>{
    const status=card.querySelector(".overview-footer > div:first-child");
    return {title:(card.querySelector(".title-text")?.textContent??"").replace(/\s+/g," ").trim(),
      href:card.getAttribute("href"),text:(status?.textContent??"").replace(/\s+/g," ").trim(),
      kind:[...(status?.classList??[])].filter((name)=>["ok","warn","bad","muted"].includes(name)).sort().join(" ")};
  }));
}

export function compareOverviewStatuses(expected:OverviewStatus[],actual:OverviewStatus[],allowFirstPage=false) {
  const expectedCount=allowFirstPage?Math.min(50,expected.length):expected.length;
  const mismatches:{index:number;expected:OverviewStatus|null;actual:OverviewStatus|null}[]=[];
  for(let index=0;index<Math.max(expectedCount,actual.length);index++) {
    const before=index<expectedCount?expected[index]!:null,after=actual[index]??null;
    if(JSON.stringify(before)!==JSON.stringify(after)||after&&(!after.title||!after.text||!after.kind))
      mismatches.push({index,expected:before,actual:after});
  }
  return {passed:mismatches.length===0,expectedCount,actualCount:actual.length,mismatches};
}
