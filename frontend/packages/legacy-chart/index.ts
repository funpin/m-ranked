import type {ChartConfiguration,ChartOptions,ChartData} from "chart.js";
import {Color} from "@kurkle/color";

type Kind="line"|"bar";
type PointStyle="circle"|"rectRot";
type XY={x:number;y:number|null};
type Dataset={label?:string;data:(XY|number|null)[];hidden?:boolean;borderColor?:string;backgroundColor?:string|string[];borderWidth?:number;pointBorderWidth?:number|number[];pointRadius?:number|number[];pointStyle?:PointStyle|PointStyle[];pointHoverRadius?:number;tension?:number;fill?:boolean;yAxisID?:string};
type Axis={type?:string;display?:boolean;position?:string;min?:number;max?:number;beginAtZero?:boolean;title?:{display?:boolean;text?:string};ticks?:{precision?:number;maxTicksLimit?:number;callback?:(value:number)=>string|number};grid?:{color?:string;drawOnChartArea?:boolean}};
type TooltipPoint={dataset:Dataset;datasetIndex:number;dataIndex:number;parsed:{x:number;y:number|null};formattedValue:string};
type Callbacks={title?:(items:TooltipPoint[])=>string|string[];label?:(item:TooltipPoint)=>string|string[];afterLabel?:(item:TooltipPoint)=>string|string[];afterTitle?:(items:TooltipPoint[])=>string|string[];afterBody?:(items:TooltipPoint[])=>string|string[]};
type Options={color?:string;scales?:Record<string,Axis>;plugins?:{tooltip?:{callbacks?:Callbacks}};onClick?:(event:Event,elements:{datasetIndex:number;index:number}[])=>void};
type Bounds={left:number;right:number;top:number;bottom:number};
type Scale={min:number;max:number;ticks:number[];labels:string[];position:string;width:number;left:number;getPixelForValue:(value:number)=>number;options:Axis};
const FONT='12px "Helvetica Neue", "Helvetica", "Arial", sans-serif';
const LINE_HEIGHT=14.4;
const numberFormat=new Intl.NumberFormat("en-US",{maximumFractionDigits:12});
const labelLines=(label:unknown):string[]=>Array.isArray(label)?label.map(String):[String(label??"")];
const crisp=(value:number,ratio:number)=>Math.round((value-.5)*ratio)/ratio+.5;
const finite=(value:number)=>Number.isFinite(value);
/** Per-point styling arrives either as one value for the series or one value per sample. */
const atPoint=<T,>(value:T|T[]|undefined,index:number,fallback:T):T=>Array.isArray(value)?value[index]??fallback:value??fallback;
const widest=(value:number|number[]|undefined,fallback:number):number=>
  Array.isArray(value)?(value.length?Math.max(...value):fallback):value??fallback;

function nice(value:number){const power=10**Math.floor(Math.log10(value||1));const fraction=value/power;return (fraction<=1?1:fraction<=2?2:fraction<=5?5:10)*power;}
export function numericTicks(low:number,high:number,limit:number,precision=12,explicitMin?:number,explicitMax?:number){
  if(!finite(low)||!finite(high)){low=0;high=1;}
  if(low===high){if(low===0)high=1;else{const offset=Math.abs(low)*.05;low-=offset;high+=offset;}}
  let spacing=nice((high-low)/Math.max(1,limit-1));
  const factor=10**precision;spacing=Math.ceil(spacing*factor)/factor;
  if(!(spacing>0))spacing=1;
  const min=explicitMin??Math.floor(low/spacing)*spacing,max=explicitMax??Math.ceil(high/spacing)*spacing;
  const ticks=[min];let value=Math.ceil(min/spacing)*spacing;
  if(Math.abs(value-min)<spacing/1000)value+=spacing;
  for(let count=0;count<1000&&value<max-spacing/1000;count++,value+=spacing)ticks.push(Number(value.toPrecision(14)));
  if(max>min)ticks.push(max);
  return {min,max,ticks};
}

/** Local, versioned renderer for the legacy line/bar contract. It never aggregates or drops samples. */
export class CompactChart<T extends Kind=Kind,D=(number|null)[]> {
  static defaults={color:"#666",borderColor:"rgba(0,0,0,0.1)",plugins:{tooltip:{backgroundColor:"rgba(0,0,0,.8)",titleColor:"#fff",bodyColor:"#fff",borderColor:"rgba(0,0,0,0)",borderWidth:0}}};
  readonly data:ChartData<T,D>;
  readonly options:ChartOptions<T>;
  readonly canvas:HTMLCanvasElement;
  readonly scales:Record<string,Scale>={};
  readonly tooltip={setActiveElements:(elements:{datasetIndex:number;index:number}[],_position:{x:number;y:number})=>{void _position;this.active=elements[0]??null;}};
  private context:CanvasRenderingContext2D;
  private plane=document.createElement("canvas");
  private dataGroups:{canvas:HTMLCanvasElement;signature:string}[]=[];
  private groupGeometry="";
  private observer:ResizeObserver;
  private width=0;
  private height=0;
  private ratio=1;
  private area:Bounds={left:0,right:0,top:0,bottom:0};
  private active:{datasetIndex:number;index:number}|null=null;
  private hidden=new Map<number,boolean>();
  private geometryKey="";
  private xTicks:number[]=[];
  private xLabels:string[][]=[];
  private yScales:Scale[]=[];
  private kind:Kind;
  private disposed=false;
  private rawOptions:Options;
  // Legacy Chart.js resolves scale defaults when the chart is constructed;
  // changing the page theme updates tooltip colors but keeps these scale colors.
  private scaleColor=CompactChart.defaults.color;
  private gridColor=CompactChart.defaults.borderColor;

  constructor(canvas:HTMLCanvasElement,configuration:ChartConfiguration<T,D>){
    this.canvas=canvas;this.kind=configuration.type;this.data=configuration.data;this.options=(configuration.options??{}) as ChartOptions<T>;
    this.rawOptions=this.options as unknown as Options;
    const context=canvas.getContext("2d");if(!context)throw new Error("Canvas2D is unavailable");this.context=context;
    canvas.addEventListener("mousemove",this.mouse);canvas.addEventListener("mouseleave",this.leave);canvas.addEventListener("click",this.click);
    this.observer=new ResizeObserver(()=>{const parent=canvas.parentElement;if(parent&&(parent.clientWidth!==this.width||parent.clientHeight!==this.height||(window.devicePixelRatio||1)!==this.ratio))this.update();});this.observer.observe(canvas.parentElement!);this.update();
  }
  private get datasets(){return this.data.datasets as unknown as Dataset[];}
  private shown(index:number){return !this.hidden.get(index)&&!this.datasets[index]?.hidden;}
  setDatasetVisibility(index:number,visible:boolean){this.hidden.set(index,!visible);this.datasets[index]!.hidden=!visible;}
  setActiveElements(elements:{datasetIndex:number;index:number}[]){this.active=elements[0]??null;}
  private point(dataset:Dataset,index:number):XY {const value=dataset.data[index];return typeof value==="object"&&value!==null?value:{x:index,y:value as number|null};}
  update(_mode?:string){
    void _mode;
    if(this.disposed)return;
    const parent=this.canvas.parentElement!;
    const width=parent.clientWidth,height=parent.clientHeight;
    if(!width||!height)return;
    const ratio=window.devicePixelRatio||1;
    // An explicit update may replace values, labels, styles or axis callbacks without
    // changing array lengths. Rendering a tooltip/theme uses render() and this plane.
    const key=JSON.stringify([width,height,ratio,this.datasets,this.data.labels,this.rawOptions.scales]);
    if(key!==this.geometryKey){
      this.geometryKey=key;this.width=width;this.height=height;this.ratio=ratio;
      this.canvas.width=Math.floor(width*ratio);this.canvas.height=Math.floor(height*ratio);this.canvas.style.width=`${width}px`;this.canvas.style.height=`${height}px`;
      this.context.setTransform(ratio,0,0,ratio,0,0);this.layout();this.drawData();
    }
    this.render();
  }
  private layout(){
    const context=this.context;context.font=FONT;
    const options=this.rawOptions.scales??{},x=options.x??{},categorical=x.type!=="linear";
    const originalLabels=(this.data.labels??[]).map(labelLines);
    const labelsWidth=(labels:string[])=>Math.max(...labels.map((text)=>context.measureText(text).width),0);
    this.yScales=[];let left=0,right=0;
    const yIds=new Set(this.datasets.map((dataset)=>dataset.yAxisID??"y"));
    for(const id of yIds){
      const option=options[id]??{};let low=Infinity,high=-Infinity;
      this.datasets.forEach((dataset,index)=>{if(!this.shown(index)||(dataset.yAxisID??"y")!==id)return;for(let i=0;i<dataset.data.length;i++){const y=this.point(dataset,i).y;if(y!==null&&finite(y)){low=Math.min(low,y);high=Math.max(high,y);}}});
      if(option.beginAtZero!==false){low=Math.min(0,low);high=Math.max(0,high);}
      const ticks=numericTicks(low,high,11,option.ticks?.precision??12,option.min,option.max);
      const labels=ticks.ticks.map((value)=>String(option.ticks?.callback?option.ticks.callback(value):numberFormat.format(value)));
      const position=option.position??"left",title=option.title?.display?22.4:0;
      const width=option.display===false?0:Math.max(...labels.map((label)=>context.measureText(label).width))+14+title;
      const scale:Scale={...ticks,labels,position,width,left:0,options:option,getPixelForValue:(value)=>this.area.bottom-(value-ticks.min)/(ticks.max-ticks.min||1)*(this.area.bottom-this.area.top)};
      this.scales[id]=scale;this.yScales.push(scale);if(position==="right")right+=width;else left+=width;
    }
    let lowX=0,highX=0;for(const dataset of this.datasets)for(let index=0;index<dataset.data.length;index++){const value=this.point(dataset,index).x;if(finite(value)){lowX=Math.min(lowX,value);highX=Math.max(highX,value);}}
    const minX=x.min??lowX,maxX=x.max??highX;
    let numeric=numericTicks(minX,maxX,Math.min(11,Math.max(2,Math.ceil((this.width-left-right)/40))),x.ticks?.precision??12,minX,maxX);
    this.xTicks=categorical?originalLabels.map((_,index)=>index):numeric.ticks;
    this.xLabels=categorical?originalLabels:this.xTicks.map((value)=>[numberFormat.format(value)]);
    const maxLines=Math.max(1,...this.xLabels.map((labels)=>labels.length));
    const bottom=8+6+maxLines*LINE_HEIGHT+(x.title?.display?22.4:0);
    // A lone category is located at the first edge, so its label needs no
    // additional padding at the unused far edge of a line chart.
    const firstWidth=labelsWidth(this.xLabels[0]??[]),lastWidth=this.xLabels.length>1?labelsWidth(this.xLabels.at(-1)??[]):0;
    const firstExtra=categorical&&this.kind==="bar"?(this.width-left-right)/Math.max(1,originalLabels.length)/2:0;
    const lastExtra=firstExtra;
    const pointOverflow=this.kind==="line"?Math.max(0,...this.datasets.filter((dataset)=>dataset.data.length>0).map((dataset)=>Math.max(widest(dataset.pointRadius,3),dataset.pointHoverRadius??4)+widest(dataset.pointBorderWidth??dataset.borderWidth,1))):0;
    left=Math.max(left,firstWidth/2+3-firstExtra,pointOverflow);right=Math.max(right,lastWidth/2+3-lastExtra,pointOverflow);
    this.area={left,top:10.2,right:this.width-right,bottom:this.height-bottom};
    if(!categorical){numeric=numericTicks(minX,maxX,Math.min(11,Math.max(2,Math.ceil((this.area.right-left)/40))),x.ticks?.precision??12,minX,maxX);this.xTicks=numeric.ticks;this.xLabels=numeric.ticks.map((value)=>[numberFormat.format(value)]);}
    else{
      const maxWidth=Math.max(...originalLabels.map(labelsWidth),1)+6;
      const count=Math.min(x.ticks?.maxTicksLimit??Infinity,Math.max(1,Math.floor((this.area.right-left)/maxWidth)+1));
      const stride=Math.max(1,Math.ceil(originalLabels.length/count));
      this.xTicks=originalLabels.map((_,index)=>index).filter((index)=>index%stride===0);this.xLabels=this.xTicks.map((index)=>originalLabels[index]!);
    }
    const offset=categorical&&this.kind==="bar"?.5:0;
    this.scales.x={min:minX,max:maxX,ticks:this.xTicks,labels:this.xLabels.map((label)=>label.join("\n")),position:"bottom",left,width:this.area.right-left,options:x,
      getPixelForValue:(value)=>this.area.left+(value-minX+offset)/(maxX-minX+offset*2||1)*(this.area.right-this.area.left)};
    let occupiedLeft=this.area.left-this.yScales.filter((scale)=>scale.position!=="right").reduce((sum,scale)=>sum+scale.width,0),occupiedRight=this.area.right;
    for(const scale of this.yScales){if(scale.position==="right"){scale.left=occupiedRight;occupiedRight+=scale.width;}else{scale.left=occupiedLeft;occupiedLeft+=scale.width;}}
  }
  private drawData(){
    const plane=this.plane;plane.width=this.canvas.width;plane.height=this.canvas.height;
    // A bounded set of transparent layers avoids redrawing all 207 series when
    // one legend entry changes. Small charts use their single existing plane.
    const bytes=plane.width*plane.height*4,total=this.datasets.reduce((sum,dataset)=>sum+dataset.data.length,0);
    const maximum=Math.min(16,Math.floor(16*1024*1024/Math.max(1,bytes)));
    if(maximum<2||this.datasets.length<=16||total<=2048){this.releaseGroups();this.drawGroup(plane,0,this.datasets.length);return;}
    const groupSize=Math.ceil(this.datasets.length/maximum),count=Math.ceil(this.datasets.length/groupSize);
    const geometry=JSON.stringify([plane.width,plane.height,this.area,Object.entries(this.scales).map(([id,scale])=>[id,scale.min,scale.max,scale.left,scale.width]),groupSize]);
    if(geometry!==this.groupGeometry){this.releaseGroups();this.groupGeometry=geometry;}
    const context=plane.getContext("2d")!;
    for(let groupIndex=count-1;groupIndex>=0;groupIndex--){
      const start=groupIndex*groupSize,end=Math.min(this.datasets.length,start+groupSize),signature=JSON.stringify(this.datasets.slice(start,end));
      const group=this.dataGroups[groupIndex]??{canvas:document.createElement("canvas"),signature:""};this.dataGroups[groupIndex]=group;
      if(group.signature!==signature){group.canvas.width=plane.width;group.canvas.height=plane.height;this.drawGroup(group.canvas,start,end);group.signature=signature;}
      context.drawImage(group.canvas,0,0);
    }
  }
  private releaseGroups(){for(const group of this.dataGroups)if(group){group.canvas.width=0;group.canvas.height=0;}this.dataGroups=[];this.groupGeometry="";}
  private drawGroup(plane:HTMLCanvasElement,start:number,end:number){
    const context=plane.getContext("2d")!;context.setTransform(this.ratio,0,0,this.ratio,0,0);
    const area=this.area;
    for(let datasetIndex=end-1;datasetIndex>=start;datasetIndex--){
      if(!this.shown(datasetIndex))continue;
      const dataset=this.datasets[datasetIndex]!,scale=this.scales[dataset.yAxisID??"y"]!;
      const values=dataset.data.map((_,index)=>{const point=this.point(dataset,index);return {...point,index,px:this.scales.x!.getPixelForValue(point.x),py:point.y===null?NaN:scale.getPixelForValue(point.y)};});
      const horizontal=this.scales.x!.options,leftOverflow=horizontal.min===undefined?10:0,rightOverflow=horizontal.max===undefined?10:0;
      context.save();context.beginPath();context.rect(area.left-leftOverflow,area.top-10,area.right-area.left+leftOverflow+rightOverflow,area.bottom-area.top+20);context.clip();
      context.lineWidth=dataset.borderWidth??3;context.strokeStyle=dataset.borderColor??"#666";
      if(this.kind==="bar"){
        const peers=this.datasets.map((value,index)=>({value,index})).filter(({index})=>this.shown(index));
        const group=peers.findIndex(({index})=>index===datasetIndex),slot=(area.right-area.left)/Math.max(1,values.length),barWidth=slot*.8/peers.length*.9;
        for(const point of values){if(!finite(point.py))continue;const origin=scale.getPixelForValue(0),zero=origin+Math.sign(point.py-origin)*.5,x=point.px-slot*.4+(group+.5)*slot*.8/peers.length;
          const y=Math.min(zero,point.py),height=Math.abs(point.py-zero),color=Array.isArray(dataset.backgroundColor)?dataset.backgroundColor[point.index]:dataset.backgroundColor;
          const hovered=this.active?.datasetIndex===datasetIndex&&this.active.index===point.index;
          const border=Math.min(dataset.borderWidth??1,barWidth/2,height/2),topBorder=point.py<zero?border:0,bottomBorder=point.py>zero?border:0;
          const inner={x:x-barWidth/2+border,y:y+topBorder,width:barWidth-2*border,height:height-topBorder-bottomBorder};
          context.save();context.beginPath();context.rect(x-barWidth/2,y,barWidth,height);context.clip();
          if(border>0){context.beginPath();context.rect(x-barWidth/2,y,barWidth,height);context.rect(inner.x,inner.y,inner.width,inner.height);context.fillStyle=hovered?new Color(dataset.borderColor??"#666").saturate(.5).darken(.1).hexString():dataset.borderColor??"#666";context.fill("evenodd");}
          context.fillStyle=hovered?new Color(color??"#666").saturate(.5).darken(.1).hexString():color??"#666";context.fillRect(inner.x,inner.y,inner.width,inner.height);context.restore();
        }
      }else{
        const segments:typeof values[]=[];let segment:typeof values=[];
        for(const point of values){if(!finite(point.py)){if(segment.length)segments.push(segment);segment=[];}else segment.push(point);}if(segment.length)segments.push(segment);
        for(const points of segments){
          const path=new Path2D();path.moveTo(points[0]!.px,points[0]!.py);
          for(let index=1;index<points.length;index++){
            const previous=points[index-1]!,current=points[index]!,before=points[index-2]??previous,after=points[index+1]??current,tension=dataset.tension??0;
            if(tension){const controls=(a:typeof current,b:typeof current,c:typeof current)=>{
              const first=Math.hypot(b.px-a.px,b.py-a.py),last=Math.hypot(c.px-b.px,c.py-b.py),sum=first+last||1;
              return {beforeX:b.px-(c.px-a.px)*tension*first/sum,beforeY:Math.max(area.top,Math.min(area.bottom,b.py-(c.py-a.py)*tension*first/sum)),afterX:b.px+(c.px-a.px)*tension*last/sum,afterY:Math.max(area.top,Math.min(area.bottom,b.py+(c.py-a.py)*tension*last/sum))};};
              const a=controls(before,previous,current),b=controls(previous,current,after);path.bezierCurveTo(a.afterX,a.afterY,b.beforeX,b.beforeY,current.px,current.py);
            }else path.lineTo(current.px,current.py);
          }
          if(dataset.fill){const fill=new Path2D(path),zero=scale.getPixelForValue(Math.max(scale.min,Math.min(scale.max,0)));fill.lineTo(points.at(-1)!.px,zero);fill.lineTo(points[0]!.px,zero);fill.closePath();context.fillStyle=typeof dataset.backgroundColor==="string"?dataset.backgroundColor:"transparent";context.fill(fill);}
          context.stroke(path);
        }
        context.fillStyle=typeof dataset.backgroundColor==="string"?dataset.backgroundColor:"transparent";
        for(const point of values){if(!finite(point.py))continue;
          const radius=atPoint(dataset.pointRadius,point.index,3);
          context.lineWidth=atPoint(dataset.pointBorderWidth,point.index,dataset.borderWidth??1);
          context.beginPath();
          if(atPoint(dataset.pointStyle,point.index,"circle")==="rectRot"){
            context.moveTo(point.px,point.py-radius);context.lineTo(point.px+radius,point.py);
            context.lineTo(point.px,point.py+radius);context.lineTo(point.px-radius,point.py);
          } else context.arc(point.px,point.py,radius,0,Math.PI*2);
          context.closePath();context.fill();context.stroke();}
      }
      context.restore();
    }
  }
  render(){
    if(this.disposed||!this.width)return;
    if(this.kind==="bar")this.drawData();
    const context=this.context,{left,right,top,bottom}=this.area;
    context.clearRect(0,0,this.width,this.height);context.font=FONT;context.textBaseline="middle";
    const color=this.rawOptions.color??this.scaleColor,grid=this.gridColor;
    const line=(x1:number,y1:number,x2:number,y2:number,stroke:string)=>{context.strokeStyle=stroke;context.lineWidth=1;context.beginPath();context.moveTo(crisp(x1,this.ratio),crisp(y1,this.ratio));context.lineTo(crisp(x2,this.ratio),crisp(y2,this.ratio));context.stroke();};
    for(const scale of this.yScales){if(!scale.width)continue;const position=scale.position==="right"?scale.left:scale.left+scale.width;
      for(const [index,tick] of scale.ticks.entries()){const y=scale.getPixelForValue(tick);if(scale.options.grid?.drawOnChartArea!==false)line(left,y,right,y,scale.options.grid?.color??grid);
        line(position,y,position+(scale.position==="right"?8:-8),y,grid);context.fillStyle=color;context.textAlign=scale.position==="right"?"left":"right";context.fillText(scale.labels[index]!,position+(scale.position==="right"?11:-11),y);
      }
      line(position,top,position,bottom,grid);
      if(scale.options.title?.display){context.save();context.fillStyle=color;context.textAlign="center";const x=scale.position==="right"?scale.left+scale.width-11.2:scale.left+11.2;context.translate(x,(top+bottom)/2);context.rotate(scale.position==="right"?Math.PI/2:-Math.PI/2);context.fillText(scale.options.title.text??"",0,0);context.restore();}
    }
    const xOption=this.scales.x!.options;
    const gridPixels=this.xTicks.map((tick)=>this.scales.x!.getPixelForValue(tick));
    for(let index=0;index<gridPixels.length+(this.kind==="bar"?1:0);index++){
      const valid=Math.min(index,gridPixels.length-1),pixel=gridPixels[valid]!;
      const offset=this.kind!=="bar"?0:gridPixels.length===1?Math.max(pixel-left,right-pixel):index===0?(gridPixels[1]!-pixel)/2:(pixel-gridPixels[valid-1]!)/2;
      const x=pixel+(valid<index?offset:-offset);
      if(x>=left-.000001&&x<=right+.000001){line(x,top,x,bottom,xOption.grid?.color??grid);line(x,bottom,x,bottom+8,grid);}
    }
    this.xTicks.forEach((tick,index)=>{const x=this.scales.x!.getPixelForValue(tick);context.fillStyle=color;context.textAlign="center";this.xLabels[index]!.forEach((label,line)=>context.fillText(label,x,bottom+18.2+line*LINE_HEIGHT));});
    line(left,bottom,right,bottom,grid);
    if(xOption.title?.display){context.fillStyle=color;context.textAlign="center";context.fillText(xOption.title.text??"",(left+right)/2,this.height-11.2);}
    context.drawImage(this.plane,0,0,this.width,this.height);
    if(this.active)this.drawTooltip();
  }
  private drawTooltip(){
    const active=this.active!,dataset=this.datasets[active.datasetIndex];if(!dataset||!this.shown(active.datasetIndex))return;
    const point=this.point(dataset,active.index);if(point.y===null&&this.kind!=="bar")return;
    const {x,y}=this.position(dataset,active.datasetIndex,active.index,true);
    const item:TooltipPoint={dataset,datasetIndex:active.datasetIndex,dataIndex:active.index,parsed:{x:point.x,y:point.y},formattedValue:point.y===null?"—":numberFormat.format(point.y)};
    const callbacks=this.rawOptions.plugins?.tooltip?.callbacks;
    const title=labelLines(callbacks?.title?.([item])??String(this.data.labels?.[active.index]??point.x));
    const body=labelLines(callbacks?.label?.(item)??`${dataset.label??""}: ${item.formattedValue}`);
    const extra=callbacks?.afterLabel?.(item),afterTitle=callbacks?.afterTitle?.([item]),afterBody=callbacks?.afterBody?.([item]);
    const titles=[...title,...(afterTitle?labelLines(afterTitle):[])],bodies=[...body,...(extra?labelLines(extra):[])],afters=afterBody?labelLines(afterBody):[];
    const context=this.context;context.font=`bold ${FONT}`;
    const titleWidth=Math.max(...titles.map((line)=>context.measureText(line).width),0);context.font=FONT;
    const width=Math.max(titleWidth,...bodies.map((line)=>context.measureText(line).width+14),...afters.map((line)=>context.measureText(line).width))+12;
    const bodyCount=bodies.length+afters.length,height=12+titles.length*LINE_HEIGHT+Math.max(0,titles.length-1)*2+(titles.length?6:0)+bodyCount*LINE_HEIGHT+Math.max(0,bodyCount-1)*2;
    const vertical=y<height/2?"top":y>this.height-height/2?"bottom":"center";
    let horizontal=vertical==="center"?(x<=(this.area.left+this.area.right)/2?"left":"right"):x<=width/2?"left":x>=this.width-width/2?"right":"center";
    if(horizontal==="left"&&x+width+7>this.width||horizontal==="right"&&x-width-7<0)horizontal="center";
    let left=x-(horizontal==="right"?width:horizontal==="center"?width/2:0);
    if(vertical==="center")left+=horizontal==="left"?7:horizontal==="right"?-7:0;else left+=horizontal==="left"?-11:horizontal==="right"?11:0;
    left=Math.max(0,Math.min(this.width-width,left));
    const top=Math.max(0,Math.min(this.height-height,y+(vertical==="top"?7:vertical==="bottom"?-height-7:-height/2)));
    if(this.kind==="line"){context.beginPath();context.arc(x,y,dataset.pointHoverRadius??4,0,Math.PI*2);context.fillStyle=typeof dataset.backgroundColor==="string"?dataset.backgroundColor:"transparent";context.strokeStyle=dataset.borderColor??"#666";context.lineWidth=atPoint(dataset.pointBorderWidth,active.index,dataset.borderWidth??1);context.fill();context.stroke();}
    const settings=CompactChart.defaults.plugins.tooltip;
    context.fillStyle=settings.backgroundColor;context.beginPath();context.roundRect(left,top,width,height,6);context.fill();
    // Tooltip spacing/alignment follows the legacy Chart.js 4.4.7 visual contract.
    // The optional caret stays inside the same canvas and uses the same fill.
    context.beginPath();
    if(vertical==="center"){const edge=horizontal==="left"?left:left+width,sign=horizontal==="left"?-1:1;context.moveTo(edge,y-5);context.lineTo(edge+sign*5,y);context.lineTo(edge,y+5);}
    else {const edge=vertical==="top"?top:top+height,sign=vertical==="top"?-1:1;context.moveTo(x-5,edge);context.lineTo(x,edge+sign*5);context.lineTo(x+5,edge);}
    context.closePath();context.fill();
    if(settings.borderWidth){context.strokeStyle=settings.borderColor;context.lineWidth=settings.borderWidth;context.beginPath();context.roundRect(left,top,width,height,6);context.stroke();}
    context.textAlign="left";context.textBaseline="middle";let lineY=top+6;
    context.fillStyle=settings.titleColor;context.font=`bold ${FONT}`;
    titles.forEach((line)=>{context.fillText(line,left+6,lineY+LINE_HEIGHT/2);lineY+=LINE_HEIGHT+2;});if(titles.length)lineY+=4;
    context.fillStyle="#fff";context.fillRect(left+6,lineY+1.2,12,12);context.strokeStyle=dataset.borderColor??"#666";context.lineWidth=dataset.borderWidth??1;context.strokeRect(left+6,lineY+1.2,12,12);
    context.fillStyle=Array.isArray(dataset.backgroundColor)?dataset.backgroundColor[active.index]!:dataset.backgroundColor??"transparent";context.fillRect(left+7,lineY+2.2,10,10);
    context.font=FONT;context.fillStyle=settings.bodyColor;
    bodies.forEach((line)=>{context.fillText(line,left+20,lineY+LINE_HEIGHT/2);lineY+=LINE_HEIGHT+2;});afters.forEach((line)=>{context.fillText(line,left+6,lineY+LINE_HEIGHT/2);lineY+=LINE_HEIGHT+2;});
  }
  private position(dataset:Dataset,datasetIndex:number,index:number,tooltip=false){const point=this.point(dataset,index),scale=this.scales[dataset.yAxisID??"y"]!;let x=this.scales.x!.getPixelForValue(point.x),y=scale.getPixelForValue(point.y??0);
    if(this.kind==="bar"){const peers=this.datasets.map((_,index)=>index).filter((index)=>this.shown(index)),group=peers.indexOf(datasetIndex),slot=(this.area.right-this.area.left)/Math.max(1,dataset.data.length);x+=-slot*.4+(group+.5)*slot*.8/peers.length;if(!tooltip)y=(y+scale.getPixelForValue(0))/2;}return {x,y};}
  private mouse=(event:MouseEvent)=>{
    // Native offset coordinates retain the browser's subpixel scroll conversion;
    // clientY minus DOMRect loses that precision when MouseEvent.clientY truncates.
    const x=Math.round(event.offsetX),y=Math.round(event.offsetY);let closest=Infinity,active:typeof this.active=null;
    this.datasets.forEach((dataset,datasetIndex)=>{if(!this.shown(datasetIndex))return;for(let index=0;index<dataset.data.length;index++){const point=this.point(dataset,index);if(point.y===null&&this.kind!=="bar")continue;const {x:px,y:py}=this.position(dataset,datasetIndex,index),distance=(px-x)**2+(py-y)**2;if(distance<closest){closest=distance;active={datasetIndex,index};}}});
    this.active=active;this.render();
  };
  private leave=()=>{this.active=null;this.render();};
  private click=(event:MouseEvent)=>{this.mouse(event);this.rawOptions.onClick?.(event,this.active?[this.active]:[]);};
  destroy(){this.disposed=true;this.observer.disconnect();this.canvas.removeEventListener("mousemove",this.mouse);this.canvas.removeEventListener("mouseleave",this.leave);this.canvas.removeEventListener("click",this.click);this.releaseGroups();this.plane.width=0;this.plane.height=0;this.context.clearRect(0,0,this.width,this.height);}
}
export default CompactChart;
