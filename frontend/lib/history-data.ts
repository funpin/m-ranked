import type { HistorySnapshot } from "./types";

/** Exact elapsed wall-clock time for a chart observation. Once a full day has
 *  elapsed, keep days separate so the clock portion remains easy to scan. */
export function elapsedSincePublication(publishedAt:string,observedAt:string):string|null {
  const published=Date.parse(publishedAt),observed=Date.parse(observedAt);
  if(!Number.isFinite(published)||!Number.isFinite(observed)||observed<published)return null;
  const seconds=Math.floor((observed-published)/1000);
  const days=Math.floor(seconds/86400);
  const hours=Math.floor(seconds%86400/3600);
  const minutes=Math.floor(seconds%3600/60);
  const clock=`${days ? String(hours).padStart(2,"0") : hours}:${String(minutes).padStart(2,"0")}:${String(seconds%60).padStart(2,"0")}`;
  return `+${days ? `${days} д ` : ""}${clock}`;
}

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
export function sampleHistory<T extends {snapshotId:string}>(rows: readonly T[], start: number, end: number, selectedId?: string, preserveIds: readonly string[] = []): T[] {
  const slice = rows.slice(start,end+1);
  if (slice.length <= 144) return slice;
  const indexes = new Set(Array.from({length:143},(_,index) => Math.round(index*(slice.length-1)/142)));
  const selected = selectedId ? slice.findIndex((row) => row.snapshotId === selectedId) : -1;
  if(selected >= 0) indexes.add(selected);
  for (const id of preserveIds) {
    const evidence = slice.findIndex((row) => row.snapshotId === id);
    if (evidence >= 0) indexes.add(evidence);
  }
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

/** Ответ API идёт от новых точек к старым; страница работает от старых к новым,
 *  при равном времени — по номеру снимка. */
export function chronological<T extends {observedAt:string;snapshotId:string}>(items: readonly T[]): T[] {
  return [...items].sort((a,b) => Date.parse(a.observedAt) - Date.parse(b.observedAt)
    || a.snapshotId.localeCompare(b.snapshotId, undefined, { numeric: true }));
}

export type HistoryPreview = {
  rows: HistorySnapshot[];
  /** Точки графика на всём диапазоне; null — отдана вся история. */
  sampledIds: string[] | null;
  totalPoints: number;
};

/** Сколько истории страница отдаёт в первом ответе.
 *
 *  24.09.2026 обход GPTBot показал цену полной истории: 280 замеров давали
 *  750 КБ HTML, из них 454 КБ — данные для гидратации всех строк, хотя график
 *  рисует не больше 144 точек, а таблица — последние сто строк. Теперь в
 *  первый ответ уходят ровно эти 144 точки графика (без интервала сборщика —
 *  он нужен только таблице) и полные строки таблицы плюс одна перед ними для
 *  прироста первой строки. Остальное браузер догружает, когда понадобится.
 *  Происхождение снимка (rawEvidence) страница не показывает — не отдаётся. */
export function previewHistory(items: readonly HistorySnapshot[], tableLimit: number): HistoryPreview {
  const clean = items.map((row) => row.rawEvidence && Object.keys(row.rawEvidence).length ? { ...row, rawEvidence: {} } : row);
  const sampled = sampleHistory(clean, 0, clean.length - 1);
  const tail = clean.slice(-(tableLimit + 1));
  if (sampled.length + tail.length >= clean.length) return { rows: clean, sampledIds: null, totalPoints: clean.length };
  const table = new Set(tail.map((row) => row.snapshotId));
  const chart = new Set(sampled.map((row) => row.snapshotId));
  return {
    rows: clean.filter((row) => table.has(row.snapshotId) || chart.has(row.snapshotId))
      .map((row) => table.has(row.snapshotId) ? row : { ...row, collectorInterval: null }),
    sampledIds: sampled.map((row) => row.snapshotId),
    totalPoints: clean.length,
  };
}
