"use client";

import { useCallback, useDeferredValue, useId, useMemo, useRef, useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceDot, XAxis, YAxis } from "recharts";
import { ChartContainer, ChartTooltip, type ChartConfig } from "@/components/ui/chart";
import { comparisonEvidence, comparisonRows, seriesKey } from "@/lib/comparison-chart-data";
import { useComparisonVisibility } from "./comparison-visibility";
import { cn } from "@/lib/utils";
import { formatCoverage, formatMetric, formatPercentage } from "@/lib/format";
import { metricNumber } from "@/lib/params";
import type { ComparisonPoint, ComparisonSeries } from "@/lib/types";

/** Eighteen separated hues, cycled. One line per selected entity. */
const SERIES_COLORS = Array.from({ length: 18 }, (_, index) => `var(--chart-${index + 1})`);

/** Axis ceiling, rounded the way the inherited plot rounded it. */
function niceCeiling(value: number) {
  if (!Number.isFinite(value) || value <= 0) return 1;
  const power = 10 ** Math.floor(Math.log10(value));
  const fraction = value / power;
  return (fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10) * power;
}

export function ComparisonChart({
  series, horizonHours, maximumHour: providedMaximumHour, label, axisLabel = label,
  metricWord = "реакций", valueFormat = "metric", cohortKind = "primary", showLegend = true,
}: {
  series: ComparisonSeries[]; horizonHours: number; label: string;
  axisLabel?: string; metricWord?: string; maximumHour?: number;
  valueFormat?: "metric" | "percentage"; cohortKind?: "primary" | "engagement"; showLegend?: boolean;
}) {
  const { hidden, toggle } = useComparisonVisibility();
  // The legend reacts at once while the plot, which is the expensive half,
  // catches up in a lower priority render.
  const deferredHidden = useDeferredValue(hidden);
  const id = useId();
  const plot = useRef<HTMLDivElement>(null);
  const [tooltip, setTooltip] = useState<string | null>(null);
  const [focused, setFocused] = useState<{ selectionId: string; hour: number } | null>(null);

  const lastObserved = useMemo(() => {
    let last = 1;
    for (const item of series) for (const point of item.points) if (point.value !== null) last = Math.max(last, point.hourOffset);
    return last;
  }, [series]);
  const maximumHour = Math.min(horizonHours, providedMaximumHour ?? lastObserved + 1);

  const rows = useMemo(() => comparisonRows(series, maximumHour), [series, maximumHour]);
  const evidence = useMemo(() => comparisonEvidence(series), [series]);

  const config = useMemo(() => {
    const value: ChartConfig = {};
    series.forEach((item, index) => {
      value[seriesKey(item.selectionId)] = { label: item.selectionLabel, color: SERIES_COLORS[index % SERIES_COLORS.length] };
    });
    return value;
  }, [series]);

  // An explicit ceiling keeps the value/pixel mapping known, which is what the
  // tooltip uses to resolve which line the pointer is nearest.
  const axisMaximum = useMemo(() => {
    let highest = 0;
    for (const row of rows) for (const item of series) {
      const candidate = row[seriesKey(item.selectionId)];
      if (typeof candidate === "number") highest = Math.max(highest, candidate);
    }
    return niceCeiling(highest);
  }, [rows, series]);

  const show = useCallback(
    (value: number | null) => (valueFormat === "percentage" ? formatPercentage(value) : formatMetric(value)),
    [valueFormat],
  );

  const reading = useCallback((selectionId: string, hour: number) => {
    const item = series.find((candidate) => candidate.selectionId === selectionId);
    const point = evidence.get(selectionId)?.get(hour);
    if (!item || !point) return null;
    return `${item.selectionLabel} · Через ${hour} ч после публикации: ${show(point.value)} · Выборка: ${point.sampleSize}`;
  }, [series, evidence, show]);

  /** Arrow keys walk time and lines; Home and End jump to the ends. */
  function focusPoint(key?: string) {
    const visible = series.filter((item) => !hidden.has(item.selectionId));
    if (!visible.length) { setTooltip("Все линии скрыты"); setFocused(null); return; }
    let line = Math.max(0, visible.findIndex((item) => item.selectionId === focused?.selectionId));
    if (key === "ArrowDown") line = (line + 1) % visible.length;
    if (key === "ArrowUp") line = (line + visible.length - 1) % visible.length;
    const current = visible[line]!;
    const hours = current.points.filter((point) => point.value !== null).map((point) => point.hourOffset);
    if (!hours.length) { setTooltip(`${current.selectionLabel}: нет доступных точек`); setFocused(null); return; }
    let at = Math.max(0, hours.indexOf(focused?.hour ?? hours[0]!));
    if (key === "ArrowRight") at = Math.min(hours.length - 1, at + 1);
    if (key === "ArrowLeft") at = Math.max(0, at - 1);
    if (key === "Home") at = 0;
    if (key === "End") at = hours.length - 1;
    const hour = hours[at]!;
    setFocused({ selectionId: current.selectionId, hour });
    setTooltip(reading(current.selectionId, hour));
  }

  function closeTooltip() { setFocused(null); setTooltip(null); }

  const focusedIndex = focused ? series.findIndex((item) => item.selectionId === focused.selectionId) : -1;
  const focusedValue = focused ? metricNumber(evidence.get(focused.selectionId)?.get(focused.hour)?.value ?? null) : null;

  return (
    <div className="min-w-0" role="region" aria-label={label}>
      {showLegend ? (
        <div className="mb-5 grid gap-2 sm:grid-cols-2 lg:grid-cols-3" role="list" aria-label="Легенда графика">
          {series.map((item, index) => {
            const isHidden = hidden.has(item.selectionId);
            const last = item.points.filter((point) => point.value !== null).at(-1);
            const cohortSize = cohortKind === "engagement" ? item.engagementCohortSize : item.primaryCohortSize;
            return (
              <div role="listitem" key={item.selectionId}>
                <button
                  type="button"
                  aria-pressed={!isHidden}
                  aria-label={`${isHidden ? "Вернуть" : "Скрыть"} линию: ${item.selectionLabel}`}
                  title={last
                    ? `${formatMetric(last.value)} · выборка ${last.sampleSize} из ${cohortSize} · покрытие ${formatCoverage(last.coverage)}`
                    : "Нет доступных точек"}
                  onClick={() => toggle(item.selectionId)}
                  className={cn(
                    "flex w-full items-center gap-2.5 rounded-md border bg-card px-2.5 py-2 text-left text-foreground transition-colors",
                    "hover:bg-accent focus-visible:ring-ring/50 focus-visible:ring-[3px] focus-visible:outline-none",
                    isHidden && "opacity-55",
                  )}
                >
                  <span
                    aria-hidden="true"
                    className="h-6 w-[3px] shrink-0 rounded-full"
                    style={{ backgroundColor: SERIES_COLORS[index % SERIES_COLORS.length] }}
                  />
                  <span className="min-w-0 flex-1">
                    <span className={cn("block truncate font-semibold", isHidden && "line-through")}>{item.selectionLabel}</span>
                    <span className="block text-[10px] font-semibold text-muted-foreground">{cohortSize} публикаций</span>
                  </span>
                </button>
              </div>
            );
          })}
        </div>
      ) : null}

      <p id={`${id}-instructions`} className="sr-only">
        Клавиши влево и вправо выбирают время; вверх и вниз — линию. Home и End — первая и последняя точка. Escape закрывает подсказку.
      </p>

      <div
        ref={plot}
        role="img"
        tabIndex={0}
        aria-label={label}
        aria-describedby={`${id}-instructions ${id}-tooltip`}
        data-chart-ready={rows.length > 0}
        data-testid="comparison-chart"
        className="h-[400px] w-full outline-none sm:h-[460px] lg:h-[560px] focus-visible:ring-ring/50 focus-visible:ring-[3px] rounded-md"
        onFocus={() => focusPoint()}
        onBlur={closeTooltip}
        onKeyDown={(event) => {
          if (event.key === "Escape") { closeTooltip(); return; }
          if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) {
            event.preventDefault();
            focusPoint(event.key);
          }
        }}
      >
        <ChartContainer config={config} className="h-full w-full">
          <LineChart data={rows} margin={{ left: 12, right: 12, top: 8, bottom: 8 }}>
            <CartesianGrid vertical={false} />
            <XAxis
              dataKey="hour" type="number" domain={[0, maximumHour]} tickLine={false} axisLine={false} tickMargin={8}
              label={{ value: "Часов после публикации", position: "insideBottom", offset: -6, fill: "var(--muted-foreground)" }}
            />
            <YAxis
              domain={[0, axisMaximum]} tickLine={false} axisLine={false} tickMargin={8} width={56}
              tickFormatter={(value: number) => (valueFormat === "percentage" ? `${value}%` : String(value))}
              label={{ value: axisLabel, angle: -90, position: "insideLeft", style: { textAnchor: "middle" }, fill: "var(--muted-foreground)" }}
            />
            <ChartTooltip
              cursor={{ strokeDasharray: "4 4" }}
              content={(props) => (
                <NearestSeriesTooltip
                  {...props}
                  axisMaximum={axisMaximum}
                  config={config}
                  evidence={evidence}
                  hidden={deferredHidden}
                  metricWord={metricWord}
                  valueFormat={valueFormat}
                />
              )}
            />
            {series.map((item, index) => (
              <Line
                key={item.selectionId}
                dataKey={seriesKey(item.selectionId)}
                hide={deferredHidden.has(item.selectionId)}
                type="monotone"
                stroke={SERIES_COLORS[index % SERIES_COLORS.length]}
                strokeWidth={2}
                // Point markers on this plot are 337 per line; they merge into
                // noise and cost two orders of magnitude in DOM nodes.
                dot={false}
                activeDot={{ r: 4 }}
                connectNulls={false}
                isAnimationActive
                animationDuration={420}
              />
            ))}
            {focused && focusedValue !== null && focusedIndex >= 0 ? (
              <ReferenceDot
                x={focused.hour}
                y={focusedValue}
                r={6}
                fill={SERIES_COLORS[focusedIndex % SERIES_COLORS.length]}
                stroke="var(--background)"
                strokeWidth={2}
              />
            ) : null}
          </LineChart>
        </ChartContainer>
      </div>

      <div
        id={`${id}-tooltip`}
        role="tooltip"
        aria-hidden={!tooltip}
        className={cn("text-sm text-muted-foreground", tooltip ? "py-2" : "sr-only")}
      >
        {tooltip || " "}
      </div>
    </div>
  );
}

/**
 * The inherited plot resolved the pointer to the single nearest point rather
 * than listing every series crossing that hour, which at this selection size
 * would be a list of two hundred rows. The axis ceiling is fixed, so the
 * pointer's own value is known and the nearest line follows from it.
 */
function NearestSeriesTooltip({
  active, payload, label, coordinate, viewBox, axisMaximum, config, evidence, hidden, metricWord, valueFormat,
}: {
  active?: boolean;
  payload?: readonly { dataKey?: unknown; value?: unknown; name?: unknown }[];
  label?: unknown;
  coordinate?: { x?: number; y?: number };
  viewBox?: { y?: number; height?: number };
  axisMaximum: number;
  config: ChartConfig;
  evidence: Map<string, Map<number, ComparisonPoint>>;
  hidden: Set<string>;
  metricWord: string;
  valueFormat: "metric" | "percentage";
}) {
  if (!active || !payload?.length || typeof label !== "number") return null;

  const visible = payload
    .map((entry) => ({
      key: typeof entry.dataKey === "string" ? entry.dataKey : "",
      value: typeof entry.value === "number" ? entry.value : null,
    }))
    .filter((entry): entry is { key: string; value: number } =>
      entry.key !== "" && entry.value !== null && !hidden.has(entry.key.slice(1)));
  if (!visible.length) return null;

  const height = viewBox?.height ?? 0;
  const top = viewBox?.y ?? 0;
  const pointerValue = height > 0 && typeof coordinate?.y === "number"
    ? axisMaximum * (1 - (coordinate.y - top) / height)
    : null;

  const nearest = pointerValue === null
    ? visible[0]!
    : visible.reduce((best, entry) =>
        Math.abs(entry.value - pointerValue) < Math.abs(best.value - pointerValue) ? entry : best);

  const key = nearest.key;
  const selectionId = key.slice(1);
  const point = evidence.get(selectionId)?.get(label);
  const sampleSize = point?.sampleSize ?? 0;
  const plural = sampleSize === 1 ? "публикация" : sampleSize >= 2 && sampleSize <= 4 ? "публикации" : "публикаций";

  return (
    <div className="border-border/50 bg-background grid min-w-[10rem] gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs shadow-xl">
      <div className="font-medium">Через {label} ч после публикации</div>
      <div className="flex items-center gap-2">
        <span
          aria-hidden="true"
          className="h-2.5 w-2.5 shrink-0 rounded-[2px]"
          style={{ backgroundColor: config[key]?.color }}
        />
        <span className="text-muted-foreground min-w-0 flex-1 truncate">{config[key]?.label}</span>
        <span className="text-foreground font-mono font-medium tabular">
          {valueFormat === "percentage" ? `${nearest.value.toFixed(2)}%` : `${Math.round(nearest.value)} ${metricWord}`}
        </span>
      </div>
      <div className="text-muted-foreground">Выборка: {sampleSize} {plural}</div>
    </div>
  );
}
