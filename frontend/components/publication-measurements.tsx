"use client";

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import type { CompactChart as Chart } from "@mranked/legacy-chart";
import Link from "@/components/bounded-link";
import { duration, legacyDate, legacyNumber } from "@/lib/format";
import { useHistoryPreferences } from "@/lib/history-preferences";
import { historyReactionEntries, sampleHistory, signedDuration } from "@/lib/history-data";
import type { HistorySnapshot, Platform } from "@/lib/types";

import { availableHistoryMetrics, historyMetricValue, historyMetricTooltip, historyRatioTooltip,
  metricLabel, metricNoun as noun, type HistoryMetric as Metric } from "@/lib/history-metrics";

function shortDate(value:string) {return legacyDate(value).replace(/\.\d{4},/, ",");}

function Reaction({ name }: { name: string }) {
  const [failed, setFailed] = useState(false);
  if (name.startsWith("custom:") && /^\d+$/.test(name.slice(7)) && !failed) {
    // Same-origin proxy validates image type; failure remains visible and accessible.
    // eslint-disable-next-line @next/next/no-img-element
    return <img className="reaction-emoji" src={`/emoji/${name.slice(7)}`} alt="Пользовательская реакция" loading="lazy" onError={() => setFailed(true)} />;
  }
  return <>{name.startsWith("custom:") || name.startsWith("unknown:") ? "❔" : name === "paid:star" ? "⭐" : name}</>;
}

function Breakdown({ value, delta = false }: { value: ReturnType<typeof historyReactionEntries>; delta?: boolean }) {
  const entries = value ?? [];
  return <span className="reaction-list">{entries.length ? entries.map(({reaction:name,count}) => <span className="reaction-item" key={name}><Reaction name={name} /> <b>{delta && count >= 0 ? "+" : ""}{count}</b></span>) : delta || value === null ? "—" : null}</span>;
}

function MetricChart({ rows, metrics, delta, selectedId, onSelect, onActivate, platform }: {
  rows: HistorySnapshot[]; metrics: Metric[]; delta: boolean; selectedId?: string;
  onSelect: (id: string) => void; onActivate: (id: string) => void; platform:string;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const instance = useRef<Chart<"line"|"bar", (number|null)[]> | null>(null);
  const keys = useMemo(() => metrics.map((metric) => metric.key),[metrics]);
  const {hidden,setHidden,scale,setScale} = useHistoryPreferences(platform,delta,keys);
  const [ready, setReady] = useState(0);
  const [tooltip, setTooltip] = useState<string | null>(null);
  const active = useRef(0);
  const chartId = useId();

  useEffect(() => {
    let cancelled = false;
    let observer: MutationObserver | undefined;
    void import("@/lib/chart-history").then(({ default: ChartJS }) => {
      if (cancelled || !canvas.current) return;
      const applyTheme = () => {
        const light=document.documentElement.dataset.theme === "light";
        ChartJS.defaults.color=light ? "#667085" : "#98a6ba";
        ChartJS.defaults.borderColor=light ? "rgba(102,112,133,.18)" : "rgba(152,166,186,.18)";
        Object.assign(ChartJS.defaults.plugins.tooltip,{backgroundColor:light?"#161a22":"#05080d",titleColor:"#f4f7fb",bodyColor:light?"#e5eaf2":"#d8e1ed",borderColor:light?"#344054":"#33445b",borderWidth:1});
      };
      applyTheme();
      const value=(metric:Metric,index:number) => historyMetricValue(rows[index]!,metric,delta);
      const commonTitle=metrics.map((metric)=>metricLabel(metric,platform)).join(" и ");
      const axisTitle=metrics.length>2 ? delta ? "Прирост метрик" : "Метрики" : delta ? `Прирост: ${commonTitle.toLowerCase()}` : commonTitle;
      const chart = new ChartJS<"line"|"bar", (number|null)[]>(canvas.current, {
        type:delta ? "bar" : "line", data:{ labels:rows.map((row) => [shortDate(row.observedAt),row.synthetic ? "момент публикации" : `через ${duration(row.ageHours*3600)}`]), datasets:metrics.map((metric) => ({ label:`${delta ? "Прирост" : "Всего"} ${noun(metric,platform)}`,
          data:rows.map((_row,index) => value(metric,index)), borderColor:metric.color, borderWidth:delta ? 1 : 3, backgroundColor:delta ? rows.map((_row,index) => (value(metric,index) ?? 0) < 0 ? "#c13b4f" : `${metric.color}${metric.key === "views" ? "bb" : "cc"}`) : `${metric.color}${metric.key === "views" ? "1f" : "22"}`,fill:!delta,
          hidden:hidden.has(metric.key), yAxisID:scale === "auto" ? metric.key : "y", tension:.15, pointRadius:3, pointBorderWidth:1,pointHoverRadius:7, spanGaps:false,
        })) }, options:{ responsive:true,maintainAspectRatio:false,animation:false,interaction:{mode:"nearest",intersect:false},
          plugins:{legend:{display:false},tooltip:{callbacks:{
            label:(item)=>historyMetricTooltip(rows[item.dataIndex]!,metrics[item.datasetIndex]!,platform,delta),
            afterTitle:(items)=>rows[items[0]?.dataIndex ?? -1]?.synthetic ? "Момент публикации · синтетическая точка" : "",
            afterBody:(items)=>{const row=rows[items[0]?.dataIndex ?? -1];return !delta&&row ? historyRatioTooltip(row,platform) : "";},
          }}},
          scales:{ x:{title:{display:true,text:"Время замера и возраст публикации"},ticks:{maxRotation:0,autoSkip:true,maxTicksLimit:rows.length <= 16 ? rows.length : Math.min(12,Math.max(6,Math.round(120/Math.sqrt(rows.length))))}},
            ...(scale === "shared" ? { y:{beginAtZero:true,title:{display:true,text:axisTitle},ticks:{precision:0},grid:{drawOnChartArea:true}} } : Object.fromEntries(metrics.map((metric,index) => [metric.key,{position:index % 2 ? "right" : "left",display:!hidden.has(metric.key),beginAtZero:true,title:{display:true,text:metricLabel(metric,platform)},ticks:{precision:0},grid:{drawOnChartArea:index === 0}}]))),
          }, onClick:(_event, elements) => { const row = rows[elements[0]?.index ?? -1]; if (row) onActivate(row.snapshotId); },
        },
      });
      instance.current = chart;
      observer = new MutationObserver(() => { applyTheme();chart.render(); });
      observer.observe(document.documentElement,{attributes:true,attributeFilter:["data-theme"]});
      setReady(version => version + 1);
    });
    return () => { cancelled = true;observer?.disconnect();instance.current?.destroy();instance.current = null; };
  }, [rows,metrics,hidden,scale,delta,onActivate,platform]);

  useEffect(() => {
    if (!selectedId || !instance.current) return;
    const index = rows.findIndex((row) => row.snapshotId === selectedId);
    if (index < 0) return;
    active.current = index;
    const datasetIndex = metrics.findIndex((metric) => !hidden.has(metric.key));
    if (datasetIndex < 0) return;
    const elements = [{datasetIndex,index}];
    instance.current.setActiveElements(elements);
    instance.current.tooltip?.setActiveElements(elements,{x:0,y:0});instance.current.render();
  }, [selectedId,rows,metrics,hidden,ready]);

  function keyboard(key?: string) {
    if (!rows.length) return;
    if (key === "ArrowRight") active.current = Math.min(rows.length-1,active.current+1);
    if (key === "ArrowLeft") active.current = Math.max(0,active.current-1);
    if (key === "Home") active.current = 0;
    if (key === "End") active.current = rows.length-1;
    active.current = Math.max(0,Math.min(rows.length-1,active.current));
    const row = rows[active.current]!;
    onSelect(row.snapshotId);
    setTooltip([legacyDate(row.observedAt), ...metrics.filter((metric) => !hidden.has(metric.key))
      .map((metric) => historyMetricTooltip(row,metric,platform,delta)), !delta ? historyRatioTooltip(row,platform) : ""].filter(Boolean).join(" · "));
  }
  function closeTooltip() {
    instance.current?.setActiveElements([]);
    instance.current?.tooltip?.setActiveElements([],{x:0,y:0});
    instance.current?.render();
    setTooltip(null);
  }
  return <>
    <div className="post-chart-toolbar"><div className="chart-legend post-chart-legend" aria-label={delta ? "Показатели графика прироста" : "Показатели графика"}>
      {metrics.map((metric) => <button key={metric.key} type="button" className={`legend-toggle${hidden.has(metric.key) ? " is-hidden" : ""}`} aria-pressed={!hidden.has(metric.key)} onClick={() => setHidden((old) => { const next = new Set(old);if(next.has(metric.key)) next.delete(metric.key);else next.add(metric.key);return next; })}><span className="legend-swatch" style={{background:metric.color}} /><span className="legend-label">{delta ? "Прирост" : "Всего"} {noun(metric,platform)}</span></button>)}
    </div><div className="scale-mode" aria-label={delta ? "Режим масштаба прироста" : "Режим масштаба"}><span>Масштаб</span><div>{(["shared","auto"] as const).map((mode) => <button className={`scale-mode-button${scale === mode ? " active" : ""}`} aria-pressed={scale === mode} type="button" key={mode} onClick={() => setScale(mode)}>{mode === "shared" ? "1:1" : "Авто"}</button>)}</div></div></div>
    <div className="chart"><canvas ref={canvas} role="img" tabIndex={0} data-chart-ready={ready>0} aria-label={delta ? "Прирост между замерами" : "Накопление показателей"} aria-describedby={`${chartId}-instructions ${chartId}-tooltip`}
      onFocus={() => keyboard()} onKeyDown={(event) => { if(event.key === "Escape") { closeTooltip(); }else if(event.key === "Enter" || event.key === " ") { event.preventDefault();const row=rows[active.current];if(row) onActivate(row.snapshotId); }else if(["ArrowLeft","ArrowRight","Home","End"].includes(event.key)) { event.preventDefault();keyboard(event.key); } }} onBlur={closeTooltip}>Все значения доступны в таблице истории замеров.</canvas></div>
    <p id={`${chartId}-instructions`} className="sr-only">Стрелки влево и вправо выбирают замер; Home и End — первый и последний. Enter или пробел открывает соответствующую строку таблицы. Escape закрывает подсказку.</p>
    <div id={`${chartId}-tooltip`} className="chart-tooltip" role="tooltip" aria-hidden={!tooltip}>{tooltip}</div>
  </>;
}

export function PublicationMeasurements({ rows, platform, historyLimit, fullHistoryHref }: { rows: HistorySnapshot[];platform:Exclude<Platform,"all">;historyLimit:number;fullHistoryHref?:string }) {
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
  const displayed = useMemo(() => sampleHistory(rows,start,end,sampledId),[rows,start,end,sampledId]);
  const tableRows = rows.slice(-Math.max(1,tableLimit));
  const nouns=metrics.map((metric)=>noun(metric,platform));
  const phrase=nouns.length<=1 ? nouns[0] ?? "метрик" : `${nouns.slice(0,-1).join(", ")} и ${nouns.at(-1)}`;
  const tableMetrics = metrics;
  const showBreakdown = rows.some(row => (historyReactionEntries(row)?.length ?? 0)>0);
  function jump(id: string) {
    const index = rows.findIndex((row) => row.snapshotId === id);
    if(index<0) return;
    if (index < start || index > end) {setStart(Math.max(0,index-36));setEnd(Math.min(rows.length-1,index+36));}
    setSelectedId(id);
  }
  return <>
    <div className="grid"><div className="panel"><h2>Накопление {phrase}</h2><p className="panel-note">Линии построены по одним и тем же замерам. В режиме 1:1 используется общая шкала; «Авто» накладывает кривые с независимыми шкалами для сравнения их формы.</p><MetricChart rows={displayed} metrics={metrics} delta={false} selectedId={selectedId} onSelect={setSelectedId} onActivate={activate} platform={platform} /></div>
      <div className="panel"><h2>Прирост между замерами</h2><p className="panel-note">Сколько новых {phrase} появилось после предыдущего опроса. В режиме 1:1 используется общая шкала; «Авто» показывает показатели на независимых шкалах.</p><MetricChart rows={displayed} metrics={metrics} delta selectedId={selectedId} onSelect={setSelectedId} onActivate={activate} platform={platform} /></div></div>
    <div className="panel chart-range"><div className="chart-range-head"><b>Масштаб по времени</b><span>{rows.length ? `${shortDate(rows[start]!.observedAt)} — ${shortDate(rows[end]!.observedAt)} · ${end-start+1} замеров` : "Нет замеров"}</span></div><div className="dual-range"><input type="range" disabled={rows.length < 2} aria-label="Начало диапазона" min={0} max={Math.max(0,rows.length-1)} value={start} onChange={(event) => setStart(Math.min(end,Number(event.target.value)))} /><input type="range" disabled={rows.length < 2} aria-label="Конец диапазона" min={0} max={Math.max(0,rows.length-1)} value={end} onChange={(event) => setEnd(Math.max(start,Number(event.target.value)))} /></div><div className="range-notes"><p className="panel-note">Двигайте левую и правую границы. В выбранном диапазоне график показывает не более 144 равномерно распределённых замеров; при приближении детализация возвращается.</p><span className="pill hidden-points" hidden={end-start+1 <= displayed.length}>{end-start+1 > displayed.length ? `Не отображено точек: ${end-start+1-displayed.length}` : ""}</span></div></div>
    <div className="panel mt measurement-history"><h2>История замеров</h2>
      {fullHistoryHref ? <p className="panel-note">Показаны последние {tableRows.length} замеров · <Link className="history-toggle" href={fullHistoryHref}>загрузить всю историю</Link></p> : rows.length > tableRows.length ? <p className="panel-note">Показаны последние {tableRows.length} из {rows.length} замеров · <button type="button" className="history-toggle" onClick={() => setTableOverride({base:historyLimit,limit:rows.length})}>показать всю историю</button></p> : rows.length > 100 ? <p className="panel-note">Показаны все {rows.length} замеров · <button type="button" className="history-toggle" onClick={() => setTableOverride({base:historyLimit,limit:100})}>свернуть историю</button></p> : null}
      {rows.length ? <div className="measurement-history-scroll"><table className="snapshot-history-table"><thead><tr>{[
        ["🕒","Время замера, МСК"],["⏱","От прошлого замера"],["⌛","После публикации"],
        ...tableMetrics.flatMap((metric) => [[metric.icon,metricLabel(metric,platform)],[`Δ${metric.icon}`,`Дельта ${noun(metric,platform)}`],...(telegram && metric.key === "reactions" ? [["👥","Минимум людей"]] : [])]),
        ...(showBreakdown ? [["😀","Реакции по типам"],["Δ😀","Дельта реакций по типам"]] : []),
      ].map(([icon,label]) => <th key={label}><span className="table-column-icon" tabIndex={0} role="img" aria-label={label} title={label}>{icon}</span></th>)}</tr></thead><tbody>
        {tableRows.map((row,index) => {
          const previous = rows[rows.length-tableRows.length+index-1];
          const elapsed = previous ? (Date.parse(row.observedAt)-Date.parse(previous.observedAt))/1000 : null;
          return <tr id={`snapshot-${row.snapshotId}`} key={row.snapshotId} className={`snapshot-row${row.synthetic ? " synthetic-row" : ""}${selectedId === row.snapshotId ? " snapshot-highlight" : ""}`} title={`${row.quality}${row.intervalUncertain ? " · интервал неопределён" : ""}`}><td><button type="button" className="snapshot-jump" title="Показать эту точку на графике" onClick={() => jump(row.snapshotId)}>{legacyDate(row.observedAt)}</button></td><td>{signedDuration(elapsed)}</td><td>{row.synthetic ? "момент публикации" : duration(row.ageHours*3600)}</td>
            {tableMetrics.map((metric) => <MetricCells key={metric.key} row={row} metric={metric} people={telegram && metric.key === "reactions"} />)}
            {showBreakdown ? <><td className="reaction-cell"><Breakdown value={historyReactionEntries(row)} /></td><td className="reaction-cell"><Breakdown value={historyReactionEntries(row,true)} delta /></td></> : null}</tr>;
        })}
      </tbody></table></div> : <div className="empty-state">Замеров ещё нет.</div>}
    </div>
  </>;
}

function MetricCells({ row,metric,people }: {row:HistorySnapshot;metric:Metric;people:boolean}) {
  const delta = row[metric.delta];
  return <><td title={row[metric.key].quality ?? undefined}>{legacyNumber(row[metric.key].value)}</td><td>{delta === null ? "—" : `${delta >= 0 ? "+" : ""}${delta}`}</td>{people ? <td>{delta === null ? "—" : delta > 0 ? `≥${Math.ceil(delta/3)}` : "0"}</td> : null}</>;
}
