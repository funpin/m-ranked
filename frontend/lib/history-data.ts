import type { HistorySnapshot } from "./types";
export function signedDuration(seconds:number|null):string {
  if(seconds===null) return "—";
  const rounded=Math.round(seconds),sign=rounded>=0?"+":"-";
  let remaining=Math.abs(rounded);
  const parts:string[]=[];
  for(const [size,label] of [[86400,"д"],[3600,"ч"],[60,"мин"],[1,"сек"]] as const) {
    const value=Math.floor(remaining/size);remaining%=size;
    if(value || (size===1 && !parts.length)) parts.push(`${value} ${label}`);
  }
  return sign+parts.join(" ");
}
/** Preserve endpoints and the chosen observation within the 144 visible point limit. */
export function sampleHistory<T extends {snapshotId:string}>(rows: readonly T[], start: number, end: number, selectedId?: string): T[] {
  const slice = rows.slice(start,end+1);
  if (slice.length <= 144) return slice;
  const indexes = new Set(Array.from({length:143},(_,index) => Math.round(index*(slice.length-1)/142)));
  const selected = selectedId ? slice.findIndex((row) => row.snapshotId === selectedId) : -1;
  if(selected >= 0) indexes.add(selected);
  return [...indexes].sort((a,b) => a-b).map((index) => slice[index]!);
}
export function historyReactionEntries(current: Pick<HistorySnapshot,"reactionsBreakdown"|"reactionsBreakdownEntries"|"deltaReactionsBreakdown"|"deltaReactionsBreakdownEntries">, delta=false) {
  const ordered=delta?current.deltaReactionsBreakdownEntries:current.reactionsBreakdownEntries;
  if(ordered!==undefined)return ordered;
  // Compatibility with an older representation preserves provided keys. Missing
  // stored deltas are unknown; adjacent canonical observations cannot recover them.
  const values=delta?current.deltaReactionsBreakdown:current.reactionsBreakdown;
  return values==null?null:Object.entries(values).map(([reaction,count])=>({reaction,count}));
}
