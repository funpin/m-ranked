"use client";

import { useEffect, useId, useRef, useState } from "react";
import type { CompactChart as Chart } from "@mranked/legacy-chart";
import { comparisonPointSegments } from "@/lib/comparison-chart-data";
import { useComparisonVisibility } from "./comparison-visibility";
import { formatCoverage, formatMetric, formatPercentage } from "@/lib/format";
import { metricNumber } from "@/lib/params";
import type { ComparisonSeries } from "@/lib/types";

const COLORS = ["#0868df", "#16a085", "#e67e22", "#c13b4f", "#7b61c9", "#00838f", "#ef6c00", "#5c6bc0", "#2e7d32", "#ad1457", "#6d4c41", "#3949ab", "#00897b", "#f4511e", "#8e24aa", "#039be5", "#7cb342", "#d81b60"];
type Point = { x: number; y: number | null };
type LineChart = Chart<"line", Point[]>;

export function ComparisonChart({ series, horizonHours, maximumHour:providedMaximumHour,label, axisLabel=label, metricWord="реакций", valueFormat = "metric", cohortKind = "primary", showLegend = true }: {
  series: ComparisonSeries[]; horizonHours: number; label: string;
  axisLabel?:string;metricWord?:string;maximumHour?:number;
  valueFormat?: "metric" | "percentage"; cohortKind?: "primary" | "engagement"; showLegend?: boolean;
}) {
  const { hidden, toggle } = useComparisonVisibility();
  const hiddenRef = useRef(hidden);
  const canvas = useRef<HTMLCanvasElement>(null);
  const chart = useRef<LineChart | null>(null);
  const active = useRef({ datasetIndex: 0, index: 0 });
  const [ready, setReady] = useState(false);
  const [tooltip, setTooltip] = useState<string | null>(null);
  const id = useId();

  useEffect(() => {
    let cancelled = false;
    let observer: MutationObserver | undefined;
    // The local, pinned legacy version is loaded only by routes with charts.
    void import("@/lib/chart-line").then(({ default: ChartJS }) => {
      if (cancelled || !canvas.current) return;
      const css = getComputedStyle(document.documentElement);
      const applyTheme=()=>{const light=document.documentElement.dataset.theme==="light";ChartJS.defaults.color=light?"#667085":"#98a6ba";ChartJS.defaults.borderColor=light?"rgba(102,112,133,.18)":"rgba(152,166,186,.18)";Object.assign(ChartJS.defaults.plugins.tooltip,{backgroundColor:light?"#161a22":"#05080d",titleColor:"#f4f7fb",bodyColor:light?"#e5eaf2":"#d8e1ed",borderColor:light?"#344054":"#33445b",borderWidth:1});};
      applyTheme();
      let lastObserved=1;for(const item of series)for(const point of item.points)if(point.value!==null)lastObserved=Math.max(lastObserved,point.hourOffset);
      const maximumHour = Math.min(horizonHours,providedMaximumHour??lastObserved+1);
      const instance = new ChartJS<"line", Point[]>(canvas.current, {
        type: "line",
        data: { datasets: series.map((item, index) => ({ label: item.selectionLabel,
          data: comparisonPointSegments(item.points).flatMap((segment, segmentIndex) => [
            ...(segmentIndex ? [{ x: segment[0]!.hourOffset - 0.5, y: null }] : []),
            ...segment.map((point) => ({ x: point.hourOffset, y: point.numericValue })),
          ]),
          hidden: hiddenRef.current.has(item.selectionId), borderColor: COLORS[index % COLORS.length], backgroundColor: `${COLORS[index % COLORS.length]}22`,
          spanGaps: false, tension: 0.15, pointRadius: 4, pointHoverRadius: 7, borderWidth: 3,
        })) },
        options: { responsive: true, maintainAspectRatio: false, animation: false, parsing: false,
          color: css.getPropertyValue("--muted"), interaction: { mode: "nearest", intersect: false },
          plugins: { legend: { display: false }, tooltip: { callbacks: {
            title: (items) => items.length ? `Через ${items[0]!.parsed.x} ч после публикации` : "",
            label: (item) => `${item.dataset.label}: ${valueFormat === "percentage" ? `${item.parsed.y?.toFixed(2)}%` : `${Math.round(item.parsed.y ?? 0)} ${metricWord}`}`,
            afterLabel: (item) => { const count=series[item.datasetIndex]?.points.find((point) => point.hourOffset === item.parsed.x)?.sampleSize ?? 0;return `Выборка: ${count} ${count===1 ? "публикация" : count>=2&&count<=4 ? "публикации" : "публикаций"}`; },
          } } },
          scales: { x: { type: "linear", min: 0, max: maximumHour, title: { display: true, text: "Часов после публикации" }, ticks: { precision: 0 } },
            y: { beginAtZero: true, title: { display: true, text: axisLabel }, ticks: valueFormat === "percentage" ? { callback: value => `${value}%` } : { precision: 0 } } },
        },
      });
      chart.current = instance;
      observer = new MutationObserver(() => {
        applyTheme();
        // The inherited chart keeps resolved scale colors on a theme toggle.
        instance.render();
      });
      observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
      setReady(true);
    });
    return () => { cancelled = true; observer?.disconnect(); chart.current?.destroy(); chart.current = null; };
  }, [series, horizonHours,providedMaximumHour,label,axisLabel,metricWord,valueFormat]);

  useEffect(() => {
    hiddenRef.current = hidden;
    series.forEach((item, index) => chart.current?.setDatasetVisibility(index, !hidden.has(item.selectionId)));
    chart.current?.update("none");
  }, [hidden, series]);

  function focusPoint(key?: string) {
    const instance = chart.current;
    if (!instance) return;
    const visible = series.map((item, index) => ({ item, index })).filter(({ item }) => !hidden.has(item.selectionId));
    if (!visible.length) { setTooltip("Все линии скрыты"); return; }
    let selected = Math.max(0, visible.findIndex(({ index }) => index === active.current.datasetIndex));
    if (key === "ArrowDown") selected = (selected + 1) % visible.length;
    if (key === "ArrowUp") selected = (selected + visible.length - 1) % visible.length;
    const current = visible[selected]!;
    const points = current.item.points.map((point, index) => ({ point, index })).filter(({ point }) => point.value !== null);
    if (!points.length) { setTooltip(`${current.item.selectionLabel}: нет доступных точек`); return; }
    let index = Math.max(0, points.findIndex((point) => point.index === active.current.index));
    if (key === "ArrowRight") index = Math.min(points.length - 1, index + 1);
    if (key === "ArrowLeft") index = Math.max(0, index - 1);
    if (key === "Home") index = 0;
    if (key === "End") index = points.length - 1;
    const selectedPoint = points[index]!;
    active.current = { datasetIndex: current.index, index: selectedPoint.index };
    const point = selectedPoint.point;
    const x = instance.scales.x!.getPixelForValue(point.hourOffset);
    const y = instance.scales.y!.getPixelForValue(metricNumber(point.value)!);
    const chartIndex = instance.data.datasets[current.index]!.data.findIndex((candidate) => candidate.x === point.hourOffset);
    const chartPoint = { datasetIndex: current.index, index: chartIndex };
    instance.setActiveElements([chartPoint]);
    instance.tooltip?.setActiveElements([chartPoint], { x, y });
    // Active elements and tooltip already have their current coordinates.
    instance.render();
    setTooltip(`${current.item.selectionLabel} · Через ${point.hourOffset} ч после публикации: ${valueFormat === "percentage" ? formatPercentage(point.value) : formatMetric(point.value)} · Выборка: ${point.sampleSize}`);
  }

  function closeTooltip() {
    chart.current?.setActiveElements([]);
    chart.current?.tooltip?.setActiveElements([], { x: 0, y: 0 });
    chart.current?.render();
    setTooltip(null);
  }

  return <div className="compare-chart-wrap" role="region" aria-label={label}>
    {showLegend ? <div className="chart-legend" role="list" aria-label="Легенда графика">
      {series.map((item, index) => {
        const last = item.points.filter((point) => point.value !== null).at(-1);
        const cohortSize = cohortKind === "engagement" ? item.engagementCohortSize : item.primaryCohortSize;
        return <div role="listitem" key={item.selectionId}><button type="button" className="legend-toggle" aria-pressed={!hidden.has(item.selectionId)}
          aria-label={`${hidden.has(item.selectionId) ? "Вернуть" : "Скрыть"} линию: ${item.selectionLabel}`} onClick={() => toggle(item.selectionId)} title={last ? `${formatMetric(last.value)} · выборка ${last.sampleSize} из ${cohortSize} · покрытие ${formatCoverage(last.coverage)}` : "Нет доступных точек"}>
          <span className="legend-swatch" style={{ backgroundColor: COLORS[index % COLORS.length] }} aria-hidden="true" />
          <span className="legend-label">{item.selectionLabel}</span><small>{cohortSize} публикаций</small>
        </button></div>;
      })}
    </div> : null}
    <p id={`${id}-instructions`} className="sr-only">Клавиши влево и вправо выбирают время; вверх и вниз — линию. Home и End — первая и последняя точка. Escape закрывает подсказку.</p>
    <div className="local-chart"><canvas ref={canvas} role="img" tabIndex={0} aria-label={label} aria-describedby={`${id}-instructions ${id}-tooltip`} data-chart-ready={ready}
      onFocus={() => focusPoint()} onBlur={closeTooltip} onKeyDown={(event) => {
        if (event.key === "Escape") { closeTooltip(); return; }
        if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) { event.preventDefault(); focusPoint(event.key); }
      }}>Значения и размер выборки каждого ряда приведены в легенде выше.</canvas></div>
    <div id={`${id}-tooltip`} role="tooltip" className="chart-tooltip" aria-hidden={!tooltip}>{tooltip || "\u00a0"}</div>
  </div>;
}
