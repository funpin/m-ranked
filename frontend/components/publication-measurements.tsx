"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { Skeleton } from "@/components/ui/skeleton";
import { observationGaps } from "@/lib/observation-gaps";
import Link from "@/components/native-link";
import { duration, legacyDate, legacyNumber } from "@/lib/format";
import { useHistoryPreferences } from "@/lib/history-preferences";
import { historyReactionEntries, sampleHistory, signedDuration } from "@/lib/history-data";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Slider } from "@/components/ui/slider";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { cn } from "@/lib/utils";
import type { HistorySnapshot, Platform, PublicationAnomalyAnalysis } from "@/lib/types";

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

const PublicationPlot = dynamic(() => import("./publication-plot"), {
  ssr: false,
  loading: () => <Skeleton className="h-[360px] w-full" role="status" aria-label="Загрузка графика" />,
});

function MetricChart(props: {
  rows: HistorySnapshot[]; metrics: Metric[]; delta: boolean; selectedId?: string;
  onSelect: (id: string) => void; onActivate: (id: string) => void; platform:string;evidenceIds:ReadonlySet<string>;
}) {
  const { metrics, platform, delta } = props;
  const keys = useMemo(() => metrics.map((metric) => metric.key), [metrics]);
  const { hidden, setHidden, scale, setScale } = useHistoryPreferences(platform, delta, keys);
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
              onClick={() => setHidden((old) => { const next = new Set(old);if(next.has(metric.key)) next.delete(metric.key);else next.add(metric.key);return next; })}
              className={cn(
                "text-foreground flex items-center gap-2 rounded-md border bg-card px-2.5 py-1.5 text-xs font-semibold transition-colors",
                "hover:bg-accent focus-visible:ring-ring/50 focus-visible:ring-[3px] focus-visible:outline-none",
                isHidden && "opacity-55",
              )}
            >
              <span aria-hidden="true" className="size-2.5 shrink-0 rounded-full" style={{ background: metric.color }} />
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
            if (value === "shared" || value === "auto") setScale(value);
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

export function PublicationMeasurements({ rows, platform, historyLimit, analysis=null, fullHistoryHref }: { rows: HistorySnapshot[];platform:Exclude<Platform,"all">;historyLimit:number;analysis?:PublicationAnomalyAnalysis|null;fullHistoryHref?:string }) {
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
  const evidenceIds = useMemo(()=>new Set(analysis?.findings.flatMap(finding=>[finding.startSnapshotId,finding.endSnapshotId].filter((id):id is string=>id!==null))??[]),[analysis]);
  const displayed = useMemo(() => sampleHistory(rows,start,end,sampledId,[...evidenceIds]),[rows,start,end,sampledId,evidenceIds]);
  const tableRows = rows.slice(-Math.max(1,tableLimit));
  const nouns=metrics.map((metric)=>noun(metric,platform));
  const phrase=nouns.length<=1 ? nouns[0] ?? "метрик" : `${nouns.slice(0,-1).join(", ")} и ${nouns.at(-1)}`;
  const tableMetrics = useMemo(() => tabulatedHistoryMetrics(rows),[rows]);
  const showBreakdown = rows.some(row => (historyReactionEntries(row)?.length ?? 0)>0);
  const gaps = useMemo(() => observationGaps(rows),[rows]);
  const gapSeconds = gaps.reduce((total,gap) => total+(gap.to-gap.from)/1000,0);
  function jump(id: string) {
    const index = rows.findIndex((row) => row.snapshotId === id);
    if(index<0) return;
    if (index < start || index > end) {setStart(Math.max(0,index-36));setEnd(Math.min(rows.length-1,index+36));}
    setSelectedId(id);
  }
  const maximum = Math.max(0, rows.length - 1);
  return <>
    <div className="grid gap-4 xl:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle as="h2" className="font-heading text-lg">Накопление {phrase}</CardTitle>
          <p className="text-muted-foreground mt-2 text-sm">Линии построены по одним и тем же замерам. Точки расставлены по времени замера, поэтому паузы в наблюдении видны как пустые промежутки. Ромбами с усиленной обводкой отмечены границы опубликованных сигналов. В режиме 1:1 используется общая шкала; «Авто» накладывает кривые с независимыми шкалами для сравнения их формы.</p>
        </CardHeader>
        <CardContent>
          <MetricChart rows={displayed} metrics={metrics} delta={false} selectedId={selectedId} onSelect={setSelectedId} onActivate={activate} platform={platform} evidenceIds={evidenceIds} />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle as="h2" className="font-heading text-lg">Прирост между замерами</CardTitle>
          <p className="text-muted-foreground mt-2 text-sm">Сколько новых {phrase} появилось после предыдущего опроса. Ромбами с усиленной обводкой отмечены границы сигналов. В режиме 1:1 используется общая шкала; «Авто» показывает показатели на независимых шкалах.</p>
        </CardHeader>
        <CardContent>
          <MetricChart rows={displayed} metrics={metrics} delta selectedId={selectedId} onSelect={setSelectedId} onActivate={activate} platform={platform} evidenceIds={evidenceIds} />
        </CardContent>
      </Card>
    </div>

    <Card className="mt-4">
      <CardContent>
        <div data-testid="chart-range-head" className="text-muted-foreground flex flex-wrap items-baseline justify-between gap-3 text-xs">
          <b className="text-foreground text-sm">Масштаб по времени</b>
          <span className="tabular">{rows.length ? `${shortDate(rows[start]!.observedAt)} — ${shortDate(rows[end]!.observedAt)} · ${end-start+1} замеров` : "Нет замеров"}</span>
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
          {gaps.length ? <p data-observation-gaps={gaps.length} className="text-muted-foreground text-sm">Пропуски в наблюдении: {gaps.length}, суммарно {duration(gapSeconds)}. На графиках они показаны заштрихованными промежутками.</p> : null}
          <p className="text-muted-foreground text-sm">Двигайте левую и правую границы. В выбранном диапазоне график показывает не более 144 равномерно распределённых замеров; при приближении детализация возвращается.</p>
          {end-start+1 > displayed.length ? <Badge variant="secondary" className="w-fit rounded-full font-semibold">Не отображено точек: {end-start+1-displayed.length}</Badge> : null}
        </div>
      </CardContent>
    </Card>

    <Card className="mt-4 overflow-hidden">
      <CardHeader>
        <CardTitle as="h2" className="font-heading text-lg">История замеров</CardTitle>
        {fullHistoryHref && rows.length > tableRows.length ? <p className="text-muted-foreground mt-2 text-sm">Показаны последние {tableRows.length} из {rows.length} замеров · <Link className="text-foreground underline underline-offset-2" href={fullHistoryHref}>загрузить всю историю</Link></p> : rows.length > tableRows.length ? <p className="text-muted-foreground mt-2 text-sm">Показаны последние {tableRows.length} из {rows.length} замеров · <button type="button" className="bg-transparent text-foreground underline underline-offset-2" onClick={() => setTableOverride({base:historyLimit,limit:rows.length})}>показать всю историю</button></p> : rows.length > 100 ? <p className="text-muted-foreground mt-2 text-sm">Показаны все {rows.length} замеров · <button type="button" className="bg-transparent text-foreground underline underline-offset-2" onClick={() => setTableOverride({base:historyLimit,limit:100})}>свернуть историю</button></p> : null}
      </CardHeader>
      <CardContent>
        {rows.length ? <div className="max-h-[70vh] isolate overflow-auto overscroll-contain rounded-lg border"><table data-testid="snapshot-history-table" className="w-max min-w-0 border-separate border-spacing-0 text-xs"><thead><tr>{[
          ["🕒","Время замера, МСК"],["⏱","От прошлого замера"],["⌛","После публикации"],
          ...tableMetrics.flatMap((metric) => [[metric.icon,metricLabel(metric,platform)],[`Δ${metric.icon}`,`Дельта ${noun(metric,platform)}`],...(telegram && metric.key === "reactions" ? [["👥","Минимум людей"]] : [])]),
          ...(showBreakdown ? [["😀","Реакции по типам"],["Δ😀","Дельта реакций по типам"]] : []),
        ].map(([icon,label]) => <th key={label} className="bg-card sticky top-0 z-[5] h-[38px] px-1.5 py-1.5 text-center shadow-[0_1px_0_var(--border)]"><span className="border-input bg-muted text-foreground focus:ring-ring/50 inline-grid h-7 min-w-7 cursor-help place-items-center rounded-md border px-1 text-base leading-none font-black outline-none focus:ring-[3px]" tabIndex={0} role="img" aria-label={label} title={label}>{icon}</span></th>)}</tr></thead><tbody>
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
                "border-border scroll-mt-[38px] border-b transition-colors [&>td]:px-1.5 [&>td]:py-1.5 [&>td]:whitespace-nowrap",
                row.synthetic && "bg-muted/40",
                boundary && "shadow-[inset_4px_0_var(--chart-4)]",
                selected && "bg-chart-3/20 shadow-[inset_4px_0_var(--chart-3)]",
              )}
              title={`${row.quality}${row.intervalUncertain ? " · интервал неопределён" : ""}${boundary?" · граница сигнала":""}`}
            ><td><button type="button" data-testid="snapshot-jump" className={cn("bg-transparent underline underline-offset-2", selected ? "text-foreground" : "text-muted-foreground hover:text-foreground", boundary && "font-black decoration-double")} title="Показать эту точку на графике" onClick={() => jump(row.snapshotId)}>{legacyDate(row.observedAt)}{boundary?<span className="sr-only">, граница сигнала аномальной динамики</span>:null}</button></td><td className="tabular">{signedDuration(elapsed)}</td><td className="tabular">{row.synthetic ? "момент публикации" : duration(row.ageHours*3600)}</td>
              {tableMetrics.map((metric) => <MetricCells key={metric.key} row={row} metric={metric} people={telegram && metric.key === "reactions"} />)}
              {showBreakdown ? <><td className="min-w-max"><Breakdown value={historyReactionEntries(row)} /></td><td className="min-w-max"><Breakdown value={historyReactionEntries(row,true)} delta /></td></> : null}</tr>;
          })}
        </tbody></table></div> : <p className="text-muted-foreground py-6 text-center">Замеров ещё нет.</p>}
      </CardContent>
    </Card>
  </>;
}

function MetricCells({ row,metric,people }: {row:HistorySnapshot;metric:Metric;people:boolean}) {
  const delta = row[metric.delta];
  return <><td className="tabular" title={row[metric.key].quality ?? undefined}>{legacyNumber(row[metric.key].value)}</td><td className="tabular">{delta === null ? "—" : `${delta >= 0 ? "+" : ""}${delta}`}</td>{people ? <td className="tabular">{delta === null ? "—" : delta > 0 ? `≥${Math.ceil(delta/3)}` : "0"}</td> : null}</>;
}
