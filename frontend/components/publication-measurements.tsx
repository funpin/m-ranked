"use client";

import { type ReactNode, Suspense, useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import dynamic from "next/dynamic";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Activity, Clock, Eye, Heart, Hourglass, MessageCircle, Share2, Smile, Timer, Users, type LucideIcon } from "lucide-react";
import Link from "@/components/native-link";
import { duration, legacyDate, legacyNumber } from "@/lib/format";
import { useHistoryPreferences } from "@/lib/history-preferences";
import { chronological, historyReactionEntries, sampleHistory, signedDuration } from "@/lib/history-data";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Slider } from "@/components/ui/slider";
import { Toggle } from "@/components/ui/toggle";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { cn } from "@/lib/utils";
import { MethodNote } from "@/components/method-note";
import { collectorGapsInRange, collectorIntervalCoverage } from "@/lib/collector-coverage";
import type { CollectorCoverage, HistorySnapshot, Platform } from "@/lib/types";
import { boundarySnapshotIds, nearestSnapshot, signalMarkers, type AnalysisLoad, type SignalMarker } from "@/lib/anomaly";
import { AnomalyAnalysisSkeleton, DeferredAnomalyAnalysis } from "@/components/anomaly-analysis";
import type { ContextEvent } from "@/lib/neighbor-context";

import { availableHistoryMetrics, tabulatedHistoryMetrics, metricLabel, metricNoun as noun, type HistoryMetric as Metric } from "@/lib/history-metrics";

function shortDate(value:string) {return legacyDate(value).replace(/\.\d{4},/, ",");}

function Reaction({ name }: { name: string }) {
  const [failed, setFailed] = useState(false);
  if (name.startsWith("custom:") && /^\d+$/.test(name.slice(7)) && !failed) {
    // Same-origin proxy validates image type; failure remains visible and accessible.
    // eslint-disable-next-line @next/next/no-img-element
    return <img className="inline-block size-5 object-contain align-middle" src={`/emoji/${name.slice(7)}`} alt="Пользовательская реакция" loading="lazy" onError={() => setFailed(true)} />;
  }
  return <>{name.startsWith("custom:") || name.startsWith("unknown:") ? "❔" : name === "paid:star" ? "⭐" : name}</>;
}

function Breakdown({ value, delta = false }: { value: ReturnType<typeof historyReactionEntries>; delta?: boolean }) {
  const entries = value ?? [];
  return <span className="flex flex-nowrap items-center gap-x-1.5 gap-y-0.5">{entries.length ? entries.map(({reaction:name,count}) => <span className="bg-muted inline-flex items-center gap-1 rounded-md px-1 py-px whitespace-nowrap" key={name}><Reaction name={name} /> <b>{delta && count >= 0 ? "+" : ""}{count}</b></span>) : delta || value === null ? "—" : null}</span>;
}

/** Заголовки колонок: монохромные значки вместо эмодзи. Эмодзи рисовались
 *  шрифтом системы, лезли за высоту строки и в каждой теме выглядели
 *  по-разному; название колонки читается наведением и скринридером. */
const COLUMN_ICONS: Record<string, LucideIcon> = {
  reactions: Heart, views: Eye, comments: MessageCircle, shares: Share2,
};

function ColumnHead({ icon: Icon, label, delta = false, align = "text-center" }: { icon: LucideIcon; label: string; delta?: boolean; align?: string }) {
  return (
    <th scope="col" className={cn("bg-card text-muted-foreground sticky top-0 z-[5] h-10 px-3 font-medium shadow-[inset_0_-1px_0_var(--border)]", align)}>
      <span className="inline-flex cursor-help items-center justify-center gap-0.5 align-middle" tabIndex={0} title={label}>
        <Icon className="size-4 shrink-0" aria-hidden="true" />
        {delta ? <span aria-hidden="true" className="text-[10px] leading-none font-semibold">Δ</span> : null}
        <span className="sr-only">{label}</span>
      </span>
    </th>
  );
}

function InlineHint({ children, content, testId }: { children: ReactNode; content: ReactNode; testId: string }) {
  return <TooltipProvider><Tooltip>
    <TooltipTrigger data-testid={testId}
      className="inline-flex cursor-help items-center border-0 bg-transparent p-0 font-inherit text-inherit outline-none focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-offset-2">
      {children}
    </TooltipTrigger>
    <TooltipContent className="max-w-80 text-left whitespace-normal">{content}</TooltipContent>
  </Tooltip></TooltipProvider>;
}

const PublicationPlot = dynamic(() => import("./publication-plot"), {
  ssr: false,
  loading: () => <Skeleton className="h-[360px] w-full" role="status" aria-label="Загрузка графика" />,
});

function MetricChart(props: {
  rows: HistorySnapshot[]; metrics: Metric[]; delta: boolean; selectedId?: string;
  onSelect: (id: string) => void; onActivate: (id: string) => void; platform:string;publishedAt:string;evidenceIds:ReadonlySet<string>;
  gaps: CollectorCoverage["gaps"]; markers: readonly SignalMarker[]; highlight?: string;
  preferredDefault?: Metric["key"];
}) {
  const { metrics, platform, delta, preferredDefault } = props;
  const hydrated = useSyncExternalStore(subscribeNever, () => true, () => false);
  const keys = useMemo(() => metrics.map((metric) => metric.key), [metrics]);
  const { hidden, setHidden, scale, setScale } = useHistoryPreferences(platform, delta, keys, preferredDefault);

  /** «Авто» рисует одну шкалу слева и одну справа, поэтому одновременно
   *  показываются не больше двух метрик: третья вытесняет лишнюю, а не
   *  остаётся без подписанной шкалы. Метрика, которую только что включили,
   *  не вытесняется никогда. */
  function capped(next: Set<Metric["key"]>, keep?: Metric) {
    const shown = metrics.filter((metric) => !next.has(metric.key));
    if (shown.length <= 2) return next;
    const droppable = shown.filter((metric) => metric !== keep);
    for (const metric of droppable.slice(0, shown.length - 2)) next.add(metric.key);
    return next;
  }
  return <>
    <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div className="flex min-w-0 flex-wrap gap-2" aria-label={delta ? "Показатели графика прироста" : "Показатели графика"}>
        {metrics.map((metric) => {
          const isHidden = hidden.has(metric.key);
          return (
            <Toggle
              key={metric.key}
              variant="outline"
              disabled={!hydrated}
              pressed={!isHidden}
              onPressedChange={() => setHidden((old) => {
                const next = new Set(old);
                if (next.has(metric.key)) { next.delete(metric.key); return scale === "auto" ? capped(next, metric) : next; }
                next.add(metric.key);
                return next;
              })}
              // Выключенная метрика приглушается цветом, а не прозрачностью:
              // размытый текст проваливался под порог контраста на светлой теме.
              className={cn("text-foreground gap-2 px-2.5 font-semibold", isHidden && "text-muted-foreground")}
            >
              <span aria-hidden="true" className={cn("size-2.5 shrink-0 rounded-full", isHidden && "opacity-40")} style={{ background: metric.color }} />
              <span className={cn(isHidden && "line-through")}>{delta ? "Прирост" : "Всего"} {noun(metric,platform)}</span>
            </Toggle>
          );
        })}
      </div>
      <div className="flex shrink-0 items-center gap-2" aria-label={delta ? "Режим масштаба прироста" : "Режим масштаба"}>
        <span className="text-muted-foreground text-xs font-medium">Масштаб</span>
        <ToggleGroup
          disabled={!hydrated}
          size="sm"
          variant="outline"
          spacing={0}
          value={[scale]}
          onValueChange={(next) => {
            // Base UI reports an empty selection when the pressed item is
            // toggled off; the plot always has exactly one scale mode.
            const value = next[0];
            if (value !== "shared" && value !== "auto") return;
            // Переход в «Авто» с тремя показанными метриками тоже подрезается.
            if (value === "auto") setHidden((old) => capped(new Set(old)));
            setScale(value);
          }}
        >
          <ToggleGroupItem value="shared">1:1</ToggleGroupItem>
          <ToggleGroupItem value="auto">Авто</ToggleGroupItem>
        </ToggleGroup>
      </div>
    </div>

    <PublicationPlot {...props} hidden={hidden} scale={scale} />
  </>;
}

/** Значение обещания, когда оно выполнится, — без Suspense. Графики не должны
 *  пересоздаваться при приходе анализа: иначе пропало бы всё, что пользователь
 *  успел в них переключить. */
function useSettled<T>(promise: Promise<T> | null | undefined): T | undefined {
  const [settled, setSettled] = useState<{ promise: Promise<T>; value: T }>();
  useEffect(() => {
    if (!promise) return;
    let live = true;
    void promise.then((value) => { if (live) setSettled({ promise, value }); });
    return () => { live = false; };
  }, [promise]);
  return settled && settled.promise === promise ? settled.value : undefined;
}

/** Строк таблицы в серверном ответе. Остальные дорисовываются в браузере после
 *  загрузки: серверу не нужно рисовать и отдавать сотню строк по 2,3 КБ, а
 *  роботу без скриптов хватает последних замеров. */
const SERVER_TABLE_ROWS = 20;
const subscribeNever = () => () => {};

export function PublicationMeasurements({ publicationId, rows: initialRows, sampledIds=null, totalPoints, collectorCoverage, platform, publishedAt, historyLimit, analysis=null, fullHistoryHref }: { publicationId:string;rows: HistorySnapshot[];sampledIds?:string[]|null;totalPoints?:number;collectorCoverage:CollectorCoverage;platform:Exclude<Platform,"all">;publishedAt:string;historyLimit:number;analysis?:Promise<AnalysisLoad>|null;fullHistoryHref?:string }) {
  // Страница может прийти с выборкой истории (см. previewHistory): точки графика
  // на всём диапазоне и хвост таблицы. Полная история догружается при первом
  // действии, которому она нужна: сужение диапазона, переход к точке или сигналу.
  const [loadedRows,setLoadedRows] = useState<HistorySnapshot[]|null>(null);
  const preview = loadedRows === null && sampledIds !== null;
  const rows = loadedRows ?? initialRows;
  const [start,setStart] = useState(0), [end,setEnd] = useState(Math.max(0,rows.length-1));
  const [fullState,setFullState] = useState<"idle"|"loading"|"failed">("idle");
  // На сервере — false, в браузере после гидратации — true, без лишнего рендера.
  const hydrated = useSyncExternalStore(subscribeNever, () => true, () => false);
  // Догрузка отвечает асинхронно и должна видеть последний выбранный диапазон.
  const latest = useRef({ rows, start, end, preview });
  useEffect(() => { latest.current = { rows, start, end, preview }; });
  const waiting = useRef<((full: HistorySnapshot[]) => void)[]>([]);
  const inflight = useRef(false);
  const requestFull = useCallback((then?: (full: HistorySnapshot[]) => void) => {
    if (!latest.current.preview) { then?.(latest.current.rows); return; }
    if (then) waiting.current.push(then);
    if (inflight.current) return;
    inflight.current = true;
    setFullState("loading");
    fetch(`/api/v1/publications/${publicationId}/history?limit=3000`, { headers: { accept: "application/json" } })
      .then((response) => { if (!response.ok) throw new Error(`history ${response.status}`); return response.json(); })
      .then((body: { items: HistorySnapshot[] }) => {
        const full = chronological(body.items);
        const { rows: shown, start: low, end: high } = latest.current;
        // Выбранный на выборке диапазон переносится по времени, а не по номеру точки.
        const whole = low === 0 && high === shown.length - 1;
        const from = Date.parse(shown[low]?.observedAt ?? ""), to = Date.parse(shown[high]?.observedAt ?? "");
        let first = whole ? 0 : full.findIndex((row) => Date.parse(row.observedAt) >= from);
        let last = full.length - 1;
        if (!whole) while (last > 0 && Date.parse(full[last]!.observedAt) > to) last--;
        if (first < 0) first = 0;
        setLoadedRows(full);
        setStart(first);
        setEnd(Math.max(first, last));
        setFullState("idle");
        const actions = waiting.current;
        waiting.current = [];
        for (const action of actions) action(full);
      })
      .catch(() => { inflight.current = false; waiting.current = []; setFullState("failed"); });
  }, [publicationId]);
  const [selectedId,setSelectedId] = useState<string>();
  const telegram = platform === "telegram";
  const metrics = useMemo(() => availableHistoryMetrics(rows),[rows]);
  const [tableOverride,setTableOverride] = useState<{base:number;limit:number}>();
  const tableLimit = tableOverride?.base === historyLimit ? tableOverride.limit : historyLimit;
  const [scrollRequest,setScrollRequest] = useState<{id:string}>();
  const activate = useCallback((id:string) => requestFull((list) => {
    const index=list.findIndex(row=>row.snapshotId===id);
    if(index<0) return;
    setSelectedId(id);
    setTableOverride(previous => ({base:historyLimit,limit:Math.max(
      previous?.base===historyLimit ? previous.limit : historyLimit, list.length-index)}));
    setScrollRequest({id});
  }),[requestFull,historyLimit]);
  useEffect(() => {
    if(!scrollRequest) return;
    const frame=requestAnimationFrame(() => {
      const row=document.getElementById(`snapshot-${scrollRequest.id}`);
      if(!row) return;
      row.scrollIntoView({block:"center",inline:"nearest",behavior:"instant"});
      row.querySelector<HTMLButtonElement>("button")?.focus({preventScroll:true});
      setScrollRequest((current) => current?.id === scrollRequest.id ? undefined : current);
    });
    return () => cancelAnimationFrame(frame);
  },[scrollRequest,tableOverride,rows]);
  const sampledId = end-start+1 > 144 ? selectedId : undefined;
  // Анализ приходит отдельно и страницу не задерживает: графики рисуются сразу,
  // отметки признаков появляются, когда ответ придёт. Без обещания (тихий режим
  // выкатки) отчёта нет вовсе — ни карточки, ни отметок.
  const settledAnalysis = useSettled(analysis);
  const shownAnalysis = settledAnalysis?.value ?? null;
  const evidenceIds = useMemo(()=>boundarySnapshotIds(shownAnalysis,rows),[shownAnalysis,rows]);
  const markers = useMemo(()=>signalMarkers(shownAnalysis),[shownAnalysis]);
  const contextEvents = useMemo(() => {
    const unique = new Map<string, ContextEvent>();
    for (const event of settledAnalysis?.neighborContext?.windows.flatMap((window) => window.events) ?? []) {
      unique.set(event.publicationId, event);
    }
    return [...unique.values()].sort((a, b) => Date.parse(a.publishedAt) - Date.parse(b.publishedAt));
  }, [settledAnalysis]);
  const contextViews = contextEvents.length > 0 ? "views" as const : undefined;
  const [highlight,setHighlight] = useState<string>();
  const chartEvidenceIds = useMemo(() => {
    const selected = markers.find((marker) => marker.id === highlight);
    if (!selected) return new Set<string>();
    const ids = [selected.from, selected.to].map((at) => nearestSnapshot(rows, new Date(at).toISOString())?.snapshotId);
    return new Set(ids.filter((id): id is string => Boolean(id)));
  }, [highlight, markers, rows]);
  const charts = useRef<HTMLDivElement>(null);
  const showSignal = useCallback((id:string) => {
    setHighlight(id);
    charts.current?.scrollIntoView({block:"start",behavior:window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth"});
  },[]);
  const wholeRange = start === 0 && end === rows.length - 1;
  // На выборке весь диапазон — это ровно те точки, что сервер отобрал из полной
  // истории, плюс выбранная и границы признаков, если они есть в выборке.
  const displayed = useMemo(() => {
    if (!preview || !wholeRange) return sampleHistory(rows,start,end,sampledId,[...evidenceIds]);
    const keep = new Set([...(sampledIds ?? []), ...evidenceIds, ...(selectedId ? [selectedId] : [])]);
    return rows.filter((row) => keep.has(row.snapshotId));
  },[preview,wholeRange,rows,start,end,sampledId,evidenceIds,sampledIds,selectedId]);
  const total = preview ? totalPoints ?? rows.length : rows.length;
  const rangePoints = preview && wholeRange ? total : end-start+1;
  const tableRows = rows.slice(-Math.max(1,tableLimit));
  const shownTableRows = hydrated ? tableRows : tableRows.slice(-SERVER_TABLE_ROWS);
  const nouns=metrics.map((metric)=>noun(metric,platform));
  const phrase=nouns.length<=1 ? nouns[0] ?? "метрик" : `${nouns.slice(0,-1).join(", ")} и ${nouns.at(-1)}`;
  const tableMetrics = useMemo(() => tabulatedHistoryMetrics(rows),[rows]);
  const showBreakdown = rows.some(row => (historyReactionEntries(row)?.length ?? 0)>0);
  const visibleGaps = useMemo(() => {
    if (!rows.length) return [];
    return collectorGapsInRange(collectorCoverage, rows[start]!.observedAt, rows[end]!.observedAt);
  }, [collectorCoverage, rows, start, end]);
  const coverageComplete = Boolean(rows.length && collectorCoverage.availableFrom
    && Date.parse(collectorCoverage.availableFrom) <= Date.parse(rows[start]!.observedAt)
    && Date.parse(collectorCoverage.through) >= Date.parse(rows[end]!.observedAt));
  const missingSeconds = visibleGaps.reduce((total, gap) => total + gap.missingSeconds, 0);
  function jump(id: string) {
    requestFull((list) => {
      const index = list.findIndex((row) => row.snapshotId === id);
      if(index<0) return;
      const { start: low, end: high } = latest.current;
      if (index < low || index > high) {setStart(Math.max(0,index-36));setEnd(Math.min(list.length-1,index+36));}
      setSelectedId(id);
    });
  }
  const maximum = Math.max(0, rows.length - 1);
  return <>
    {analysis ? (
      <Suspense fallback={<AnomalyAnalysisSkeleton />}>
        <DeferredAnomalyAnalysis load={analysis} rows={rows} publishedAt={publishedAt} onShow={showSignal} />
      </Suspense>
    ) : null}
    <div ref={charts} data-testid="publication-chart-stack" className="grid scroll-mt-4 gap-4">
      {markers.length ? <div className="text-muted-foreground flex flex-wrap items-center gap-x-4 gap-y-1 px-1 text-xs" aria-label="Обозначения графиков">
        {markers.some((marker) => marker.tone === "priority") ? <span><span className="text-destructive font-bold">●</span> Исходный сигнал · приоритетный</span> : null}
        {markers.some((marker) => marker.tone === "review") ? <span><span className="text-[var(--chart-3)] font-bold">●</span> Исходный сигнал · проверка</span> : null}
      </div> : null}
      <Card>
        <CardHeader>
          <CardTitle as="h2" className="font-heading flex items-center gap-1.5 text-lg">
            Накопление {phrase}
            <MethodNote title={`Накопление ${phrase}`}>
              Точки — сохранённые замеры. Полоса — интервалы сигналов; ромбы — границы выбранного сигнала. Новые публикации и их точное время показаны в строках анализа. Интервал между точками не означает простой сборщика.
            </MethodNote>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <MetricChart rows={displayed} metrics={metrics} delta={false} selectedId={selectedId} onSelect={setSelectedId} onActivate={activate} platform={platform} publishedAt={publishedAt} evidenceIds={chartEvidenceIds} gaps={visibleGaps} markers={markers} preferredDefault={contextViews} highlight={highlight} />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle as="h2" className="font-heading flex items-center gap-1.5 text-lg">
            Прирост между сохранёнными точками
            <MethodNote title="Прирост между сохранёнными точками">
              Столбец — разница сохранённых замеров, иногда нескольких опросов. Обводка — граница выбранного сигнала. Новые посты показаны в строках анализа.
            </MethodNote>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <MetricChart rows={displayed} metrics={metrics} delta selectedId={selectedId} onSelect={setSelectedId} onActivate={activate} platform={platform} publishedAt={publishedAt} evidenceIds={chartEvidenceIds} gaps={visibleGaps} markers={markers} preferredDefault={contextViews} highlight={highlight} />
        </CardContent>
      </Card>
    </div>

    <Card className="mt-4">
      <CardContent>
        <div data-testid="chart-range-head" className="text-muted-foreground flex flex-wrap items-baseline justify-between gap-3 text-xs">
          <b className="text-foreground flex items-center gap-1.5 text-sm">
            Масштаб по времени
            <MethodNote title="Масштаб по времени">
              Двигайте границы для детализации. Красное — подтверждённые пропуски сбора. Длинный интервал между точками сам по себе не означает простой.
            </MethodNote>
          </b>
          <span className="tabular">{rows.length ? `${shortDate(rows[start]!.observedAt)} — ${shortDate(rows[end]!.observedAt)} · ${rangePoints} сохранённых точек` : "Нет сохранённых точек"}</span>
        </div>
        <Slider
          className="my-4"
          disabled={rows.length < 2}
          min={0}
          max={maximum}
          step={1}
          value={[start, end]}
          onValueChange={(next) => {
            const [low, high] = next as [number, number];
            setStart(Math.min(low, high));
            setEnd(Math.max(low, high));
            // Приближение требует всех точек; пока они грузятся, диапазон
            // двигается по выборке и потом переносится по времени.
            requestFull();
          }}
          getAriaLabel={(index) => (index === 0 ? "Начало диапазона" : "Конец диапазона")}
        />
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span data-testid="sparse-history-note" className="text-muted-foreground">● Изменения + контроль</span>
          {visibleGaps.length
            ? <Badge variant="destructive" data-testid="collector-gap-summary" className="h-auto px-2.5 py-1 text-[length:inherit] tabular-nums">● Пропуски {visibleGaps.length} · {duration(missingSeconds)}</Badge>
            : coverageComplete
              ? <Badge data-testid="collector-gap-summary" className="h-auto bg-emerald-500/10 px-2.5 py-1 text-[length:inherit] font-normal text-emerald-700 dark:text-emerald-300">● Без пропусков</Badge>
              : <Badge variant="secondary" data-testid="collector-gap-summary" className="bg-muted text-muted-foreground h-auto px-2.5 py-1 text-[length:inherit] font-normal">◌ Неполный журнал</Badge>}
          <span className="text-muted-foreground tabular-nums">Циклы {collectorCoverage.successfulPolls.toLocaleString("ru-RU")} / {collectorCoverage.failedPolls.toLocaleString("ru-RU")} ошибок</span>
          {!coverageComplete && visibleGaps.length ? <span className="text-muted-foreground">◌ Часть вне журнала</span> : null}
          {fullState === "loading" ? <p data-testid="full-history-loading" className="text-muted-foreground text-sm" role="status">Загружаем все сохранённые точки…</p> : null}
          {fullState === "failed" ? <p className="text-destructive text-sm" role="status">Не удалось загрузить все точки — график показывает выборку по всему периоду.</p> : null}
          {rangePoints > displayed.length ? <Badge variant="secondary" className="w-fit rounded-full font-semibold">+{rangePoints-displayed.length} точек при приближении</Badge> : null}
        </div>
      </CardContent>
    </Card>

    <Card className="mt-4 overflow-hidden">
      <CardHeader>
        <CardTitle as="h2" className="font-heading flex items-center gap-1.5 text-lg">История сохранённых точек
          <MethodNote title="История сохранённых точек">Строки — изменения и контрольные снимки. Между ними могли быть опросы с теми же значениями.</MethodNote>
        </CardTitle>
        <div data-testid="saved-history-note" className="text-muted-foreground mt-2 flex flex-wrap items-center gap-2 text-xs">
          <span className="tabular-nums">{tableRows.length} / {Math.max(total, rows.length)} точек</span>
          {fullHistoryHref && total > tableRows.length ? <Link className="text-foreground font-medium underline underline-offset-2" href={fullHistoryHref} aria-label="загрузить всю историю">Вся история →</Link> : rows.length > tableRows.length ? <Button variant="link" className="text-foreground h-auto p-0 text-xs underline underline-offset-2" onClick={() => setTableOverride({base:historyLimit,limit:rows.length})}>Показать все →</Button> : rows.length > 100 ? <Button variant="link" className="text-foreground h-auto p-0 text-xs underline underline-offset-2" aria-label="свернуть историю" onClick={() => setTableOverride({base:historyLimit,limit:100})}>Свернуть</Button> : null}
        </div>
      </CardHeader>
      <CardContent>
        {/* relative обязателен: скрытые для глаз подписи (sr-only) — абсолютные, и
            без собственного блока позиционирования строка глубоко в таблице
            выходила из-под прокрутки и растягивала страницу на всю высоту
            таблицы — под постами с анализом оставались тысячи пикселей пустоты. */}
        {rows.length ? <div className="relative max-h-[70vh] isolate overflow-auto overscroll-contain rounded-lg border"><table data-testid="snapshot-history-table" className="w-full min-w-max border-separate border-spacing-0 text-xs"><thead><tr>{([
          { icon: Clock, label: "Время сохранённой точки, МСК" },
          { icon: Timer, label: "Между сохранёнными точками" },
          { icon: Activity, label: "Работа сборщика в интервале" },
          { icon: Hourglass, label: "После публикации" },
          ...tableMetrics.flatMap((metric) => [
            { icon: COLUMN_ICONS[metric.key] ?? Heart, label: metricLabel(metric,platform) },
            { icon: COLUMN_ICONS[metric.key] ?? Heart, label: `Прирост: ${noun(metric,platform)}`, delta: true },
            ...(telegram && metric.key === "reactions" ? [{ icon: Users, label: "Минимум людей" }] : []),
          ]),
          ...(showBreakdown ? [{ icon: Smile, label: "Реакции по типам" }, { icon: Smile, label: "Прирост реакций по типам", delta: true }] : []),
        ] as { icon: LucideIcon; label: string; delta?: boolean }[]).map((column) => <ColumnHead key={column.label} icon={column.icon} label={column.label} delta={column.delta} />)}</tr></thead><tbody>
          {shownTableRows.map((row,index) => {
            const previous = rows[rows.length-shownTableRows.length+index-1];
            const elapsed = previous ? (Date.parse(row.observedAt)-Date.parse(previous.observedAt))/1000 : null;
            const selected = selectedId === row.snapshotId;
            const boundary = evidenceIds.has(row.snapshotId);
            return <tr
              id={`snapshot-${row.snapshotId}`}
              key={row.snapshotId}
              data-selected={selected || undefined}
              data-anomaly-boundary={boundary || undefined}
              className={cn(
                "scroll-mt-10 transition-colors hover:bg-muted/50 [&>td]:border-b [&>td]:border-border [&>td]:px-3 [&>td]:py-2 [&>td]:whitespace-nowrap",
                row.synthetic && "bg-muted/40",
                boundary && "shadow-[inset_4px_0_var(--chart-4)]",
                selected && "bg-chart-3/20 shadow-[inset_4px_0_var(--chart-3)]",
              )}
            ><td><button type="button" data-testid="snapshot-jump" className={cn("bg-transparent underline underline-offset-2", selected ? "text-foreground" : "text-muted-foreground hover:text-foreground", boundary && "font-black decoration-double")} title="Показать эту точку на графике" onClick={() => jump(row.snapshotId)}>{legacyDate(row.observedAt)}{boundary?<span className="sr-only">, граница сигнала аномальной динамики</span>:null}</button></td><td className="tabular text-right">{elapsed === null ? signedDuration(elapsed) : <InlineHint testId="saved-point-interval" content="Интервал между сохранёнными изменениями. Это не простой: опросы без изменений не сохраняются.">{signedDuration(elapsed)}</InlineHint>}</td><CollectorIntervalCell row={row} coverage={collectorCoverage} /><td className="tabular text-right">{row.synthetic ? "момент публикации" : duration(row.ageHours*3600)}</td>
              {tableMetrics.map((metric) => <MetricCells key={metric.key} row={row} metric={metric} people={telegram && metric.key === "reactions"} />)}
              {showBreakdown ? <><td className="min-w-max"><Breakdown value={historyReactionEntries(row)} /></td><td className="min-w-max"><Breakdown value={historyReactionEntries(row,true)} delta /></td></> : null}</tr>;
          })}
        </tbody></table></div> : <p className="text-muted-foreground py-6 text-center">Сохранённых точек ещё нет.</p>}
      </CardContent>
    </Card>
  </>;
}

function CollectorIntervalCell({ row, coverage }: { row: HistorySnapshot; coverage: CollectorCoverage }) {
  const interval = row.collectorInterval;
  if (!interval) return <td className="text-muted-foreground min-w-44 !whitespace-normal">Нет предыдущей точки</td>;
  const state = collectorIntervalCoverage(coverage, interval.from, interval.to);
  if (state.kind === "unknown") return <td className="text-muted-foreground min-w-44 !whitespace-normal">Журнал циклов недоступен</td>;
  const summary = state.kind === "gap"
    ? `Подтверждённый пропуск: ${duration(state.missingSeconds)}. В остальное время сбор шёл.`
    : "Сбор шёл; промежуточные опросы без изменений не сохранялись.";
  return <td className="min-w-44 !whitespace-normal"><InlineHint
    testId="collector-status-trigger"
    content={`${summary} За интервал: успешных циклов — ${interval.successfulPolls}, с ошибкой — ${interval.failedPolls}.`}
  >{state.kind === "gap"
      ? <Badge variant="destructive" data-testid="collector-gap-badge">Пропуск {duration(state.missingSeconds)}</Badge>
      : <Badge variant="secondary" data-testid="collector-covered-badge">Сбор шёл</Badge>}
  </InlineHint></td>;
}

function MetricCells({ row,metric,people }: {row:HistorySnapshot;metric:Metric;people:boolean}) {
  const delta = row[metric.delta];
  return <><td className="tabular text-right">{legacyNumber(row[metric.key].value)}</td><td className="tabular text-right">{delta === null ? "—" : `${delta >= 0 ? "+" : ""}${delta}`}</td>{people ? <td className="tabular text-right">{delta === null ? "—" : delta > 0 ? `≥${Math.ceil(delta/3)}` : "0"}</td> : null}</>;
}
