import type {Page} from "@playwright/test";

export type StorageMask={key:string;x:number;y:number;width:number;height:number;reason:string};

/** Mask only live numeric text; progress graphics and all layout remain compared. */
export async function storageValues(page:Page):Promise<StorageMask[]> {
  return page.evaluate(()=>{
    const panel=[...document.querySelectorAll(".storage-panel")].find(element=>element.querySelector("h2")?.textContent==="Использование хранилища");
    if(!panel)return [];
    const results:{key:string;x:number;y:number;width:number;height:number;reason:string}[]=[];
    for(const [index,element] of [...panel.querySelectorAll(".period-badge,.storage-label b,.storage-grid small")].entries()){
      const walker=document.createTreeWalker(element,NodeFilter.SHOW_TEXT);let node:Node|null,part=0;
      while((node=walker.nextNode()))for(const match of (node.textContent??"").matchAll(/\d[\d., ]*\s*(?:[КМГТ]?Б|%)/g)){
        const range=document.createRange();range.setStart(node,match.index!);range.setEnd(node,match.index!+match[0].length);
        const key=`storage-number:${index}:${part++}`,rect=range.getBoundingClientRect();
        if(rect.width>0&&rect.height>0&&rect.bottom>0&&rect.top<innerHeight&&rect.right>0&&rect.left<innerWidth)results.push({key,x:rect.x,y:rect.y,width:rect.width,height:rect.height,reason:"Live filesystem/DB size or percentage; labels, cards and tables stay visible"});
      }
    }
    return results;
  });
}

export function pairedStorageMasks(left:StorageMask[],right:StorageMask[]) {
  const masks:StorageMask[]=[],skipped:string[]=[];
  for(const first of left){const second=right.find(row=>row.key===first.key);
    if(!second||Math.abs(first.y-second.y)>1||Math.abs(first.height-second.height)>1){skipped.push(first.key);continue;}
    // Union covers only corresponding dynamic glyphs. Vertical movement is a
    // layout mismatch and must remain visible rather than widening a mask.
    const x=Math.floor(Math.min(first.x,second.x)),y=Math.floor(Math.min(first.y,second.y));
    masks.push({...first,x,y,width:Math.ceil(Math.max(first.x+first.width,second.x+second.width))-x,height:Math.ceil(Math.max(first.y+first.height,second.y+second.height))-y});
  }
  return {masks,skipped};
}

export async function maskedStorageScreenshot(page:Page,masks:StorageMask[]) {
  await page.evaluate((rectangles)=>{for(const rectangle of rectangles){const cover=document.createElement("div");cover.dataset.visualStorageMask="true";cover.setAttribute("aria-hidden","true");Object.assign(cover.style,{position:"fixed",left:`${rectangle.x}px`,top:`${rectangle.y}px`,width:`${rectangle.width}px`,height:`${rectangle.height}px`,background:"#ff00ff",zIndex:"2147483647",pointerEvents:"none"});document.body.append(cover);}},masks);
  try{return await page.screenshot({type:"png",fullPage:false,animations:"disabled"});}
  finally{await page.evaluate(()=>document.querySelectorAll("[data-visual-storage-mask]").forEach(element=>element.remove()));}
}
