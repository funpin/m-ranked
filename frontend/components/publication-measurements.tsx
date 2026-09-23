"use client";

import { type ReactNode, useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import dynamic from "next/dynamic";
import { Skeleton } from "@/components/ui/skeleton";
import { Activity, Clock, Eye, Heart, Hourglass, MessageCircle, Share2, Smile, Timer, Users, type LucideIcon } from "lucide-react";
import Link from "@/components/native-link";
import { duration, legacyDate, legacyNumber } from "@/lib/format";
import { useHistoryPreferences } from "@/lib/history-preferences";
import { historyReactionEntries, sampleHistory, signedDuration } from "@/lib/history-data";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Slider } from "@/components/ui/slider";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { cn } from "@/lib/utils";
import { MethodNote } from "@/components/method-note";
import { collectorGapsInRange, collectorIntervalCoverage } from "@/lib/collector-coverage";
import type { CollectorCoverage, HistorySnapshot, Platform, PublicationAnomalyAnalysis } from "@/lib/types";
import { boundarySnapshotIds, signalMarkers, type SignalMarker } from "@/lib/anomaly";
import { AnomalyAnalysis } from "@/components/anomaly-analysis";

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
  const tooltipId = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const [position, setPosition] = useState<{ left: number; top: number; above: boolean }>();
  const show = useCallback(() => {
    const box = trigger.current?.getBoundingClientRect();
    if (!box) return;
    const above = box.bottom + 96 > window.innerHeight;
    setPosition({
      left: Math.max(16, Math.min(window.innerWidth - 336, box.left + box.width / 2 - 160)),
      top: above ? box.top - 6 : box.bottom + 6,
      above,
    });
  }, []);
  useEffect(() => {
    if (!position) return;
    const reposition = () => show();
    window.addEventListener("resize", reposition);
    window.addEventListener("scroll", reposition, true);
    return () => {
      window.removeEventListener("resize", reposition);
      window.removeEventListener("scroll", reposition, true);
    };
  }, [position, show]);
  return <>
    <button
      ref={trigger}
      type="button"
      data-testid={testId}
      aria-describedby={tooltipId}
      onMouseEnter={show}
      onMouseLeave={() => setPosition(undefined)}
      onFocus={show}
      onBlur={() => setPosition(undefined)}
      className="inline-flex cursor-help items-center border-0 bg-transparent p-0 font-inherit text-inherit outline-none focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-offset-2"
    >{children}</button>
    {position ? createPortal(<span
      id={tooltipId}
      role="tooltip"
      className="bg-popover text-popover-foreground pointer-events-none fixed z-50 w-[calc(100vw-2rem)] max-w-80 rounded-md border px-3 py-1.5 text-left text-xs leading-relaxed whitespace-normal shadow-md"
      style={{ left: position.left, top: position.top, transform: position.above ? "translateY(-100%)" : undefined }}
    >{content}</span>, document.body) : null}
  </>;
}

const PublicationPlot = dynamic(() => import("./publication-plot"), {
  ssr: false,
  loading: () => <Skeleton className="h-[360px] w-full" role="status" aria-label="Загрузка графика" />,
});

function MetricChart(props: {
  rows: HistorySnapshot[]; metrics: Metric[]; delta: boolean; selectedId?: string;
  onSelect: (id: string) => void; onActivate: (id: string) => void; platform:string;publishedAt:string;evidenceIds:ReadonlySet<string>;
  gaps: CollectorCoverage["gaps"]; markers: readonly SignalMarker[]; highlight?: string;
}) {
  const { metrics, platform, delta } = props;
  const keys = useMemo(() => metrics.map((metric) => metric.key), [metrics]);
  const { hidden, setHidden, scale, setScale } = useHistoryPreferences(platform, delta, keys);

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
            <button
              key={metric.key}
              type="button"
              aria-pressed={!isHidden}
              onClick={() => setHidden((old) => {
                const next = new Set(old);
                if (next.has(metric.key)) { next.delete(metric.key); return scale === "auto" ? capped(next, metric) : next; }
                next.add(metric.key);
                return next;
              })}
              className={cn(
                "text-foreground flex items-center gap-2 rounded-md border bg-card px-2.5 py-1.5 text-xs font-semibold transition-colors",
                "hover:bg-accent focus-visible:ring-ring/50 focus-visible:ring-[3px] focus-visible:outline-none",
                // Выключенная метрика приглушается цветом, а не прозрачностью:
                // размытый текст проваливался под порог контраста на светлой теме.
                isHidden && "text-muted-foreground",
              )}
            >
              <span aria-hidden="true" className={cn("size-2.5 shrink-0 rounded-full", isHidden && "opacity-40")} style={{ background: metric.color }} />
              <span className={cn(isHidden && "line-through")}>{delta ? "Прирост" : "Всего"} {noun(metric,platform)}</span>
            </button>
          );
        })}
      </div>
      <div className="flex shrink-0 items-center gap-2" aria-label={delta ? "Режим масштаба прироста" : "Режим масштаба"}>
        <span className="text-muted-foreground text-xs font-medium">Масштаб</span>
        <ToggleGroup
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

export function PublicationMeasurements({ rows, collectorCoverage, platform, publishedAt, historyLimit, analysis=null, analysisFailed=false, showAnalysis=true, fullHistoryHref }: { rows: HistorySnapshot[];collectorCoverage:CollectorCoverage;platform:Exclude<Platform,"all">;publishedAt:string;historyLimit:number;analysis?:PublicationAnomalyAnalysis|null;analysisFailed?:boolean;showAnalysis?:boolean;fullHistoryHref?:string }) {
  const [start,setStart] = useState(0), [end,setEnd] = useState(Math.max(0,rows.length-1));
  const [selectedId,setSelectedId] = useState<string>();
  const telegram = platform === "telegram";
  const metrics = useMemo(() => availableHistoryMetrics(rows),[rows]);
  const [tableOverride,setTableOverride] = useState<{base:number;limit:number}>();
  const tableLimit = tableOverride?.base === historyLimit ? tableOverride.limit : historyLimit;
  const [scrollRequest,setScrollRequest] = useState<{id:string}>();
  const activate = useCallback((id:string) => {
    const index=rows.findIndex(row=>row.snapshotId===id);
    if(index<0) return;
    setSelectedId(id);
    setTableOverride(previous => ({base:historyLimit,limit:Math.max(
      previous?.base===historyLimit ? previous.limit : historyLimit, rows.length-index)}));
    setScrollRequest({id});
  },[rows,historyLimit]);
  useEffect(() => {
    if(!scrollRequest) return;
    const row=document.getElementById(`snapshot-${scrollRequest.id}`);
    row?.scrollIntoView({block:"center",inline:"nearest",behavior:window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth"});
    row?.querySelector<HTMLButtonElement>("button")?.focus({preventScroll:true});
  },[scrollRequest]);
  const sampledId = end-start+1 > 144 ? selectedId : undefined;
  // В тихом режиме выкатки отчёт скрыт целиком — и карточка, и отметки на графиках.
  const shownAnalysis = showAnalysis ? analysis : null;
  const evidenceIds = useMemo(()=>boundarySnapshotIds(shownAnalysis,rows),[shownAnalysis,rows]);
  const markers = useMemo(()=>signalMarkers(shownAnalysis),[shownAnalysis]);
  const [highlight,setHighlight] = useState<string>();
  const charts = useRef<HTMLDivElement>(null);
  const showSignal = useCallback((id:string) => {
    setHighlight(id);
    charts.current?.scrollIntoView({block:"start",behavior:window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth"});
  },[]);
  const displayed = useMemo(() => sampleHistory(rows,start,end,sampledId,[...evidenceIds]),[rows,start,end,sampledId,evidenceIds]);
  const tableRows = rows.slice(-Math.max(1,tableLimit));
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
    const index = rows.findIndex((row) => row.snapshotId === id);
    if(index<0) return;
    if (index < start || index > end) {setStart(Math.max(0,index-36));setEnd(Math.min(rows.length-1,index+36));}
    setSelectedId(id);
  }
  const maximum = Math.max(0, rows.length - 1);
  return <>
    {showAnalysis ? <AnomalyAnalysis analysis={analysis} loadFailed={analysisFailed} rows={rows} publishedAt={publishedAt} onShow={showSignal} /> : null}
    <div ref={charts} data-testid="publication-chart-stack" className="grid scroll-mt-4 gap-4">
      <Card>
        <CardHeader>
          <CardTitle as="h2" className="font-heading flex items-center gap-1.5 text-lg">
            Накопление {phrase}
            <MethodNote title={`Накопление ${phrase}`}>
              Линии построены по сохранённым изменениям метрик и контрольным снимкам. Одинаковые результаты опросов обычно не сохраняются, поэтому расстояние между точками не показывает время работы или простоя сборщика. Ромбами отмечены границы признаков анализа, полупрозрачной полосой с символом — их интервалы; остальные точки читаются по подсказке и по таблице ниже. В режиме 1:1 используется общая шкала; «Авто» даёт каждой метрике свою шкалу — слева и справа — и показывает не больше двух сразу.
            </MethodNote>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <MetricChart rows={displayed} metrics={metrics} delta={false} selectedId={selectedId} onSelect={setSelectedId} onActivate={activate} platform={platform} publishedAt={publishedAt} evidenceIds={evidenceIds} gaps={visibleGaps} markers={markers} highlight={highlight} />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle as="h2" className="font-heading flex items-center gap-1.5 text-lg">
            Прирост между сохранёнными точками
            <MethodNote title="Прирост между сохранёнными точками">
              Сколько новых {phrase} появилось между соседними сохранёнными изменениями или контрольными снимками. Это не обязательно прирост за один опрос: одинаковые результаты между точками обычно не сохраняются. Столбец с обводкой отмечает границу сигнала, отрицательный столбец — исправление источника. В режиме 1:1 используется общая шкала; «Авто» даёт каждой метрике свою шкалу — слева и справа — и показывает не больше двух сразу.
            </MethodNote>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <MetricChart rows={displayed} metrics={metrics} delta selectedId={selectedId} onSelect={setSelectedId} onActivate={activate} platform={platform} publishedAt={publishedAt} evidenceIds={evidenceIds} gaps={visibleGaps} markers={markers} highlight={highlight} />
        </CardContent>
      </Card>
    </div>

    <Card className="mt-4">
      <CardContent>
        <div data-testid="chart-range-head" className="text-muted-foreground flex flex-wrap items-baseline justify-between gap-3 text-xs">
          <b className="text-foreground flex items-center gap-1.5 text-sm">
            Масштаб по времени
            <MethodNote title="Масштаб по времени">
              Двигайте левую и правую границы. В выбранном диапазоне график показывает не более 144 равномерно распределённых сохранённых точек; при приближении детализация возвращается. Красным отмечены только подтверждённые разрывы в журнале успешных циклов аккаунта, а не длинные интервалы без изменения метрик. Близкие разрывы на общем масштабе визуально объединяются; при приближении видны их реальные границы.
            </MethodNote>
          </b>
          <span className="tabular">{rows.length ? `${shortDate(rows[start]!.observedAt)} — ${shortDate(rows[end]!.observedAt)} · ${end-start+1} сохранённых точек` : "Нет сохранённых точек"}</span>
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
          }}
          getAriaLabel={(index) => (index === 0 ? "Начало диапазона" : "Конец диапазона")}
        />
        <div className="grid gap-2">
          <p data-testid="sparse-history-note" className="text-muted-foreground text-sm">Графики показывают сохранённые изменения метрик и контрольные снимки. Опросы без изменений обычно не записываются, поэтому длинный интервал между точками сам по себе не означает, что сборщик не работал.</p>
          {visibleGaps.length
            ? <p data-testid="collector-gap-summary" className="text-destructive text-sm font-medium">Подтверждённые пропуски сбора в выбранном диапазоне: {visibleGaps.length}, суммарно {duration(missingSeconds)}. Они отмечены красным; близкие пропуски на текущем масштабе объединяются в общий блок.{coverageComplete ? "" : " Часть диапазона вне журнала: в ней наличие пропусков неизвестно."}</p>
            : coverageComplete
              ? <p data-testid="collector-gap-summary" className="text-muted-foreground text-sm">По журналу циклов аккаунта подтверждённых пропусков в выбранном диапазоне нет.</p>
              : <p data-testid="collector-gap-summary" className="text-muted-foreground text-sm">Журнал циклов покрывает выбранный диапазон не полностью — в непокрытой части наличие пропусков неизвестно.</p>}
          <p className="text-muted-foreground text-xs">В журнале от первой показанной точки до текущего среза: успешных циклов — {collectorCoverage.successfulPolls}, с ошибкой — {collectorCoverage.failedPolls}. Ожидаемый шаг — {duration(collectorCoverage.expectedIntervalSeconds)}.</p>
          {end-start+1 > displayed.length ? <Badge variant="secondary" className="w-fit rounded-full font-semibold">Не отображено точек: {end-start+1-displayed.length}</Badge> : null}
        </div>
      </CardContent>
    </Card>

    <Card className="mt-4 overflow-hidden">
      <CardHeader>
        <CardTitle as="h2" className="font-heading text-lg">История сохранённых точек</CardTitle>
        <p data-testid="saved-history-note" className="text-muted-foreground mt-2 text-sm">Каждая строка — изменение метрик или контрольный снимок. Интервал до предыдущей строки не равен простою сборщика: между строками могли быть успешные опросы с теми же значениями.</p>
        {fullHistoryHref && rows.length > tableRows.length ? <p className="text-muted-foreground mt-2 text-sm">Показаны последние {tableRows.length} из {rows.length} сохранённых точек · <Link className="text-foreground underline underline-offset-2" href={fullHistoryHref}>загрузить всю историю</Link></p> : rows.length > tableRows.length ? <p className="text-muted-foreground mt-2 text-sm">Показаны последние {tableRows.length} из {rows.length} сохранённых точек · <button type="button" className="bg-transparent text-foreground underline underline-offset-2" onClick={() => setTableOverride({base:historyLimit,limit:rows.length})}>показать всю историю</button></p> : rows.length > 100 ? <p className="text-muted-foreground mt-2 text-sm">Показаны все {rows.length} сохранённых точек · <button type="button" className="bg-transparent text-foreground underline underline-offset-2" onClick={() => setTableOverride({base:historyLimit,limit:100})}>свернуть историю</button></p> : null}
      </CardHeader>
      <CardContent>
        {rows.length ? <div className="max-h-[70vh] isolate overflow-auto overscroll-contain rounded-lg border"><table data-testid="snapshot-history-table" className="w-full min-w-max border-separate border-spacing-0 text-xs"><thead><tr>{([
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
          {tableRows.map((row,index) => {
            const previous = rows[rows.length-tableRows.length+index-1];
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
