import { duration } from "@/lib/format";
import type { HistorySnapshot } from "@/lib/types";

/** A stretch between two neighbouring samples far longer than the usual polling
 *  interval means the collectors were down. The chart marks it instead of drawing
 *  the two samples side by side as if nothing had been missed. */
const GAP_MIN_MS = 30 * 60_000;
export function observationGaps(rows: HistorySnapshot[]) {
  const gaps: {from:number;to:number;label?:string}[] = [];
  if (rows.length < 3) return gaps;
  const times = rows.map(row => Date.parse(row.observedAt));
  const steps = times.slice(1).map((value,index) => value-times[index]!).filter(step => step>0).sort((a,b)=>a-b);
  if (!steps.length) return gaps;
  const median = steps[Math.floor(steps.length/2)]!;
  const threshold = Math.max(GAP_MIN_MS, median*4);
  for (let index=1; index<times.length; index++) {
    const from=times[index-1]!, to=times[index]!;
    if (to-from >= threshold) gaps.push({from,to,label:`нет данных ${duration((to-from)/1000)}`});
  }
  return gaps;
}

